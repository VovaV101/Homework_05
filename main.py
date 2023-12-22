import names
import aiohttp
import asyncio
import json
import logging
import websockets
from websockets import WebSocketServerProtocol
from websockets.exceptions import ConnectionClosedOK
from datetime import datetime, timedelta
from aiofile import AIOFile

logging.basicConfig(level=logging.INFO)

class PrivatBankAPI:
    BASE_URL = "https://api.privatbank.ua/p24api/exchange_rates"

    @classmethod
    async def get_currency_rates(cls, date):
        url = f"{cls.BASE_URL}?json&date={date}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response_data = await response.text()
                return json.loads(response_data)

class CurrencyConverter:
    def __init__(self, target_currencies):
        self.target_currencies = target_currencies

    def convert_data(self, api_data):
        result = []

        for day_data in api_data:
            date = day_data.get('date', '')
            currencies = day_data.get('exchangeRate', [])

            currencies_info = {}
            for rate in currencies:
                currency_code = rate.get('currency')
                if currency_code in self.target_currencies:
                    currencies_info[currency_code] = {
                        'sale': rate.get('saleRateNB', ''),
                        'purchase': rate.get('purchaseRateNB', '')
                    }

            if date and currencies_info:
                result.append({date: currencies_info})

        return result

class Server:
    MAX_DAYS_ALLOWED = 10
    clients = set()
    converter = CurrencyConverter(['USD', 'EUR'])
    log_file_path = 'exchange_log.txt'

    async def register(self, ws: WebSocketServerProtocol):
        ws.name = names.get_full_name()
        self.clients.add(ws)
        logging.info(f'{ws.remote_address} connects')

    async def unregister(self, ws: WebSocketServerProtocol):
        self.clients.remove(ws)
        logging.info(f'{ws.remote_address} disconnects')

    async def send_to_clients(self, message: str):
        if self.clients:
            [await client.send(message) for client in self.clients]

    async def ws_handler(self, ws: WebSocketServerProtocol, path):
        await self.register(ws)
        try:
            await self.distribute(ws)
        except ConnectionClosedOK:
            pass
        finally:
            await self.unregister(ws)

    async def distribute(self, ws: WebSocketServerProtocol):
        async for message in ws:
            if message.startswith("exchange"):
                await self.handle_exchange_command(ws, message)
            else:
                await self.send_to_clients(f"{ws.name}: {message}")

    async def fetch_currency_rates(self, days):
        tasks = []
        async with aiohttp.ClientSession() as session:
            today = datetime.now().strftime('%d.%m.%Y')
            end_date = (datetime.now() - timedelta(days=1)).strftime('%d.%m.%Y')
            for day in range(days):
                date = (datetime.now() - timedelta(days=day)).strftime('%d.%m.%Y')
                tasks.append(PrivatBankAPI.get_currency_rates(date))
            return await asyncio.gather(*tasks)

    async def handle_exchange_command(self, ws: WebSocketServerProtocol, message):
        try:
            parts = message.split(" ")
            command = parts[0].lower()
            days = int(parts[1]) if len(parts) > 1 and parts[1] else 1  # Використовуємо 1 за замовчуванням

            if command == "exchange":
                if days > self.MAX_DAYS_ALLOWED:
                    raise ValueError(
                        f"Invalid 'exchange' command format. Maximum allowed days is {self.MAX_DAYS_ALLOWED}")

                api_data = await self.fetch_currency_rates(days)
            else:
                raise ValueError("Invalid 'exchange' command format.")

            converted_data = self.converter.convert_data(api_data)
            exchange_rate_message = json.dumps(converted_data, indent=2)

            await self.send_to_clients(exchange_rate_message)

            await self.log_exchange_command(ws.name, days)

        except ValueError as e:
            logging.error(str(e))

    async def log_exchange_command(self, username, days):
        async with AIOFile(self.log_file_path, 'a') as log_file:
            await log_file.write(f"{datetime.now()} - {username} executed 'exchange {days}' command.\n")


async def main():
    server = Server()
    async with websockets.serve(server.ws_handler, '0.0.0.0', 8080):
        await asyncio.Future()  # run forever

if __name__ == '__main__':
    asyncio.run(main())
