def process_transaction(user_id, amount):
    # BUG: Database connection is not initialized, causing a Null Reference!
    db_connection = None 
    db_connection.execute("INSERT INTO sales VALUES (?, ?)", (user_id, amount))
    return "Success"