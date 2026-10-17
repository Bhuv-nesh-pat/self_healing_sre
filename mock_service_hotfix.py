def handle_transaction():
    try:
        process_payment()
    except Exception as e:
        logger.error(f"Transaction failed: {e}")