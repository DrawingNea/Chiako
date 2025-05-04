import aiomysql
import asyncio


class DatabaseManager:
    def __init__(self, *, db_config: dict) -> None:
        self.connection = None  # Database connection
        self.db_config = db_config  # Database configuration to reconnect
        self.retry_limit = 5  # Max number of retries to reconnect

    async def reconnect(self):
        """Re-establish the connection to the database."""
        try:
            self.connection = await aiomysql.connect(**self.db_config)
            print("Database connection re-established.")
        except Exception as e:
            print(f"Failed to reconnect to the database: {e}")
            raise

    async def get_connection(self) -> aiomysql.Connection:
        """Get the current database connection or create a new one if it's not available."""
        if self.connection is not aiomysql.Connection:
            print("Connection is closed or not established. Reconnecting...")
            await self.reconnect()
        return self.connection

    async def execute_with_reconnect(self, query, params):
        """Execute a query and handle connection loss with automatic reconnection."""
        attempt = 0
        while attempt < self.retry_limit:
            try:
                async with (await self.get_connection()).cursor() as cursor:
                    await cursor.execute(query, params)
                    return cursor  # Return the cursor for further processing
            except (aiomysql.MySQLError, ConnectionError) as e:
                print(f"Error executing query: {e}. Reconnecting...")
                await self.reconnect()  # Attempt to reconnect
                attempt += 1
                await asyncio.sleep(2)  # Wait before retrying
        raise Exception("Failed to reconnect to the database after multiple attempts.")

    async def add_warn(
        self, user_id: int, server_id: int, moderator_id: int, reason: str
    ) -> int:
        """
        Add a warn to the database.
        """
        query = """
            SELECT id FROM warns WHERE user_id=%s AND server_id=%s ORDER BY id DESC LIMIT 1
        """
        params = (user_id, server_id)
        rows = await self.execute_with_reconnect(query, params)
        result = await rows.fetchone()
        warn_id = result[0] + 1 if result is not None else 1

        insert_query = """
            INSERT INTO warns(id, user_id, server_id, moderator_id, reason) 
            VALUES (%s, %s, %s, %s, %s)
        """
        insert_params = (warn_id, user_id, server_id, moderator_id, reason)
        await self.execute_with_reconnect(insert_query, insert_params)
        return warn_id

    async def remove_warn(self, warn_id: int, user_id: int, server_id: int) -> int:
        """
        Remove a warn from the database.
        """
        delete_query = """
            DELETE FROM warns WHERE id=%s AND user_id=%s AND server_id=%s
        """
        delete_params = (warn_id, user_id, server_id)
        await self.execute_with_reconnect(delete_query, delete_params)

        count_query = """
            SELECT COUNT(*) FROM warns WHERE user_id=%s AND server_id=%s
        """
        count_params = (user_id, server_id)
        rows = await self.execute_with_reconnect(count_query, count_params)
        result = await rows.fetchone()
        return result[0] if result is not None else 0

    async def get_warnings(self, user_id: int, server_id: int) -> list:
        """
        Get all the warnings of a user.
        """
        query = """
            SELECT user_id, server_id, moderator_id, reason, strftime('%s', created_at), id
            FROM warns WHERE user_id=%s AND server_id=%s
        """
        params = (user_id, server_id)
        rows = await self.execute_with_reconnect(query, params)
        result = await rows.fetchall()
        return result
