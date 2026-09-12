import json
import os
import random
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

import certifi
from dotenv import load_dotenv


# ============================================================
# НАСТРОЙКИ
# ============================================================

GROUP_ID = 530489534

# Telegram
TELEGRAM_CHAT_ID = -1004379094458

# Topics
STOCK_THREAD_ID = 2
PENDING_THREAD_ID = 3

# Твой Premium Robux custom emoji
ROBUX_EMOJI_ID = "5359666427135567162"

# Stock обновляем раз в 5 минут
STOCK_INTERVAL = 300

# Продажи проверяем раз в 2 минуты
SALES_INTERVAL = 120

# Берём только первую страницу, чтобы снизить нагрузку Roblox
MAX_SALES_PAGES = 1

# Минимальная пауза после 429
MIN_BACKOFF = 30

STATE_FILE = "bot_state.json"


# ============================================================
# ENV
# ============================================================

load_dotenv()

ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

if not ROBLOX_COOKIE:
    print("ОШИБКА: ROBLOX_COOKIE не найден в .env")
    raise SystemExit

if not TELEGRAM_TOKEN:
    print("ОШИБКА: TELEGRAM_TOKEN не найден в .env")
    raise SystemExit


# ============================================================
# SSL
# ============================================================

SSL_CONTEXT = ssl.create_default_context(
    cafile=certifi.where()
)


# ============================================================
# СОСТОЯНИЕ
# ============================================================

def create_default_state():
    return {
        "stock_message_id": None,
        "sales_initialized": False,
        "sales": {},
        "next_stock_check": 0,
        "next_sales_check": 0,
        "backoff_until": 0,
        "backoff_seconds": MIN_BACKOFF,
    }


def load_state():
    if not os.path.exists(STATE_FILE):
        return create_default_state()

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            state = json.load(file)

        default = create_default_state()

        for key, value in default.items():
            if key not in state:
                state[key] = value

        return state

    except Exception as error:
        print(f"[STATE] Не удалось прочитать {STATE_FILE}: {error}")
        return create_default_state()


def save_state(state):
    temp_file = STATE_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2
        )

    os.replace(temp_file, STATE_FILE)


# ============================================================
# RATE LIMIT ROBLOX
# ============================================================

def set_backoff_from_429(error, state):
    retry_after = error.headers.get("Retry-After")
    reset_after = error.headers.get("x-ratelimit-reset")

    wait_seconds = None

    if retry_after:
        try:
            wait_seconds = float(retry_after)
        except ValueError:
            pass

    if wait_seconds is None and reset_after:
        try:
            wait_seconds = float(reset_after)
        except ValueError:
            pass

    if wait_seconds is None:
        wait_seconds = state["backoff_seconds"]

        state["backoff_seconds"] = min(
            state["backoff_seconds"] * 2,
            600
        )

    wait_seconds = max(
        MIN_BACKOFF,
        wait_seconds
    )

    wait_seconds += random.uniform(1, 3)

    state["backoff_until"] = (
        time.time() + wait_seconds
    )

    save_state(state)

    print(
        f"[429] Roblox ограничил запросы. "
        f"Ожидание: {wait_seconds:.1f} сек."
    )


# ============================================================
# ROBLOX HTTP
# ============================================================

def roblox_get(url, state):
    request = urllib.request.Request(
        url,
        headers={
            "Cookie": f".ROBLOSECURITY={ROBLOX_COOKIE}",
            "User-Agent": "RobloxSalesBot/1.0",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=20,
            context=SSL_CONTEXT,
        ) as response:

            state["backoff_seconds"] = MIN_BACKOFF
            save_state(state)

            return json.loads(
                response.read().decode("utf-8")
            )

    except urllib.error.HTTPError as error:

        if error.code == 429:
            set_backoff_from_429(error, state)
            raise RuntimeError("ROBLOX_RATE_LIMIT")

        body = error.read().decode(
            "utf-8",
            errors="replace",
        )

        raise RuntimeError(
            f"Roblox HTTP {error.code}: {body}"
        )

    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Ошибка подключения к Roblox: {error}"
        )


# ============================================================
# GROUP BALANCE
# ============================================================

def get_group_balance(state):
    url = (
        f"https://economy.roblox.com/"
        f"v1/groups/{GROUP_ID}/currency"
    )

    data = roblox_get(url, state)

    return int(data["robux"])


# ============================================================
# PENDING BALANCE
# ============================================================

def get_pending_balance(state):
    url = (
        f"https://economy.roblox.com/"
        f"v1/groups/{GROUP_ID}/revenue/summary/Day"
    )

    data = roblox_get(url, state)

    return int(
        data.get("pendingRobux", 0)
    )


# ============================================================
# TRANSACTIONS
# ============================================================

def get_sales_page(state):
    params = {
        "transactionType": "Sale",
        "limit": "10",
        "sortOrder": "Desc",
    }

    url = (
        f"https://economy.roblox.com/"
        f"v2/groups/{GROUP_ID}/transactions?"
        f"{urllib.parse.urlencode(params)}"
    )

    return roblox_get(url, state)


def get_recent_sales(state):
    data = get_sales_page(state)

    sales = data.get("data", [])

    print(
        f"[ROBLOX] Получено транзакций: {len(sales)}"
    )

    return sales


# ============================================================
# TELEGRAM HTTP
# ============================================================

def telegram_request(method, data):
    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/{method}"
    )

    encoded = urllib.parse.urlencode(
        data
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=encoded,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=20,
            context=SSL_CONTEXT,
        ) as response:

            result = json.loads(
                response.read().decode("utf-8")
            )

            if not result.get("ok"):
                raise RuntimeError(
                    f"Telegram error: {result}"
                )

            return result["result"]

    except urllib.error.HTTPError as error:

        body = error.read().decode(
            "utf-8",
            errors="replace",
        )

        raise RuntimeError(
            f"Telegram HTTP {error.code}: {body}"
        )

    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Ошибка подключения к Telegram: {error}"
        )


# ============================================================
# STOCK
# ============================================================

def build_stock_text(balance, pending):
    robux_emoji = (
        f'<tg-emoji emoji-id="{ROBUX_EMOJI_ID}">💸</tg-emoji>'
    )

    return (
        "<blockquote>"
        f"<b>{balance}</b> {robux_emoji}\n"
        f"<b>⏳ {pending}</b> {robux_emoji}"
        "</blockquote>"
    )


def create_stock_message(state, balance, pending):
    message = telegram_request(
        "sendMessage",
        {
            "chat_id": TELEGRAM_CHAT_ID,
            "message_thread_id": STOCK_THREAD_ID,
            "text": build_stock_text(
                balance,
                pending,
            ),
            "parse_mode": "HTML",
        },
    )

    state["stock_message_id"] = (
        message["message_id"]
    )

    save_state(state)

    print(
        f"[STOCK] Создано сообщение "
        f"#{message['message_id']}"
    )


def update_stock_message(state, balance, pending):
    message_id = state.get(
        "stock_message_id"
    )

    if not message_id:
        create_stock_message(
            state,
            balance,
            pending,
        )
        return

    try:
        telegram_request(
            "editMessageText",
            {
                "chat_id": TELEGRAM_CHAT_ID,
                "message_id": message_id,
                "text": build_stock_text(
                    balance,
                    pending,
                ),
                "parse_mode": "HTML",
            },
        )

        print(
            f"[STOCK] {balance} Robux | "
            f"pending {pending} Robux"
        )

    except RuntimeError as error:

        error_text = str(error).lower()

        # Telegram сообщает, что сообщение не изменилось
        if "message is not modified" in error_text:
            print(
                f"[STOCK] без изменений: "
                f"{balance} Robux | "
                f"pending {pending} Robux"
            )
            return

        # Сообщение удалили
        if (
            "message to edit not found" in error_text
            or "message_id_invalid" in error_text
        ):
            print(
                "[STOCK] Сообщение удалено. "
                "Создаём новое."
            )

            state["stock_message_id"] = None
            save_state(state)

            create_stock_message(
                state,
                balance,
                pending,
            )

            return

        raise


# ============================================================
# ВРЕМЯ
# ============================================================

def format_time(iso_time):
    try:
        dt = datetime.fromisoformat(
            iso_time.replace(
                "Z",
                "+00:00",
            )
        )

        return dt.astimezone().strftime(
            "%d.%m.%Y %H:%M:%S"
        )

    except Exception:
        return iso_time


# ============================================================
# НОВАЯ ПОКУПКА
# ============================================================

def build_pending_message(sale):
    accessory = sale["details"]["name"]
    price = sale["currency"]["amount"]
    created = format_time(
        sale["created"]
    )

    robux_emoji = (
        f'<tg-emoji emoji-id="{ROBUX_EMOJI_ID}">💸</tg-emoji>'
    )

    return (
        f"<b>{accessory}</b>\n"
        f"+{price} {robux_emoji}\n"
        f"🕐 {created}"
    )


def send_pending_message(sale):
    telegram_request(
        "sendMessage",
        {
            "chat_id": TELEGRAM_CHAT_ID,
            "message_thread_id": PENDING_THREAD_ID,
            "text": build_pending_message(
                sale
            ),
            "parse_mode": "HTML",
        },
    )

    print(
        f"[SALE] "
        f"{sale['details']['name']} | "
        f"+{sale['currency']['amount']} Robux"
    )


# ============================================================
# INITIALIZE SALES
# ============================================================

def initialize_sales(state, sales):
    if state["sales_initialized"]:
        return

    print(
        "[INIT] Сохраняю существующие "
        "транзакции без старых уведомлений."
    )

    for sale in sales:

        state["sales"][
            sale["idHash"]
        ] = {
            "is_pending": sale.get(
                "isPending",
                False,
            ),
            "created": sale.get(
                "created"
            ),
        }

    state["sales_initialized"] = True

    save_state(state)

    print(
        f"[INIT] Сохранено: {len(sales)}"
    )


# ============================================================
# PROCESS SALES
# ============================================================

def process_sales(state, sales):
    changed = False

    # Сначала старые, потом новые
    sales = sorted(
        sales,
        key=lambda sale: sale.get(
            "created",
            ""
        ),
    )

    for sale in sales:

        sale_id = sale["idHash"]

        current_pending = sale.get(
            "isPending",
            False,
        )

        # ==========================================
        # НОВАЯ ПРОДАЖА
        # ==========================================

        if sale_id not in state["sales"]:

            state["sales"][sale_id] = {
                "is_pending": current_pending,
                "created": sale.get(
                    "created"
                ),
            }

            changed = True

            # Одно уведомление на одну покупку
            send_pending_message(sale)

            continue

        # ==========================================
        # УЖЕ ИЗВЕСТНАЯ ПРОДАЖА
        # ==========================================

        previous_pending = (
            state["sales"][sale_id].get(
                "is_pending",
                False,
            )
        )

        # ==========================================
        # PENDING -> COMPLETED
        # ==========================================

        if (
            previous_pending
            and not current_pending
        ):

            print(
                f"[COMPLETED] "
                f"{sale['details']['name']} | "
                f"{sale['currency']['amount']} Robux"
            )

            state["sales"][sale_id][
                "is_pending"
            ] = False

            changed = True

            continue

        # Синхронизация статуса
        if previous_pending != current_pending:

            state["sales"][sale_id][
                "is_pending"
            ] = current_pending

            changed = True

    if changed:
        save_state(state)


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 55)
    print("ROBLOX SALES BOT")
    print("=" * 55)
    print(f"Group ID: {GROUP_ID}")
    print(f"Stock interval: {STOCK_INTERVAL} sec")
    print(f"Sales interval: {SALES_INTERVAL} sec")
    print("Transaction pages: 1")
    print()

    state = load_state()

    now = time.time()

    # При старте сразу делаем обе проверки
    state["next_stock_check"] = now
    state["next_sales_check"] = now

    save_state(state)

    while True:

        now = time.time()

        # ==========================================
        # RATE LIMIT
        # ==========================================

        if now < state["backoff_until"]:

            remaining = int(
                state["backoff_until"] - now
            )

            print(
                f"[RATE LIMIT] "
                f"ждём ещё {remaining} сек."
            )

            time.sleep(
                min(
                    10,
                    max(1, remaining),
                )
            )

            continue

        try:

            # ======================================
            # STOCK
            # ======================================

            if now >= state["next_stock_check"]:

                print("[STOCK] обновление...")

                balance = get_group_balance(
                    state
                )

                pending = get_pending_balance(
                    state
                )

                update_stock_message(
                    state,
                    balance,
                    pending,
                )

                state["next_stock_check"] = (
                    time.time()
                    + STOCK_INTERVAL
                )

                save_state(state)

            # ======================================
            # SALES
            # ======================================

            if now >= state["next_sales_check"]:

                print(
                    "[SALES] проверка транзакций..."
                )

                sales = get_recent_sales(
                    state
                )

                if not state["sales_initialized"]:

                    initialize_sales(
                        state,
                        sales
                    )

                else:

                    process_sales(
                        state,
                        sales
                    )

                state["next_sales_check"] = (
                    time.time()
                    + SALES_INTERVAL
                )

                save_state(state)

        except RuntimeError as error:

            # 429
            if str(error) == "ROBLOX_RATE_LIMIT":
                continue

            print()
            print("[ОШИБКА]")
            print(error)
            print()

            state["backoff_until"] = (
                time.time() + 30
            )

            save_state(state)

        except Exception as error:

            print()
            print("[НЕОЖИДАННАЯ ОШИБКА]")
            print(error)
            print()

            state["backoff_until"] = (
                time.time() + 30
            )

            save_state(state)

        # Не нагружаем процессор
        time.sleep(5)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()