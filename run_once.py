import time

import main


def run_once():
    print("=== ROBLOX SALES BOT: ONE RUN ===")

    state = main.load_state()

    # На случай rate limit от предыдущего запуска
    if time.time() < state.get("backoff_until", 0):
        remaining = int(
            state["backoff_until"] - time.time()
        )

        print(
            f"Rate limit active. "
            f"Ждём ещё {remaining} сек."
        )

        return

    try:
        # ----------------------------------------
        # STOCK
        # ----------------------------------------

        print("[STOCK] Проверка...")

        balance = main.get_group_balance(state)
        pending = main.get_pending_balance(state)

        main.update_stock_message(
            state,
            balance,
            pending
        )

        # ----------------------------------------
        # SALES
        # ----------------------------------------

        print("[SALES] Проверка...")

        sales = main.get_recent_sales(state)

        print(
            f"[SALES] Получено транзакций: "
            f"{len(sales)}"
        )

        if not state["sales_initialized"]:
            main.initialize_sales(
                state,
                sales
            )
        else:
            main.process_sales(
                state,
                sales
            )

        print("=== Готово ===")

    except Exception as error:
        print("[ОШИБКА]")
        print(error)
        raise


if __name__ == "__main__":
    run_once()
