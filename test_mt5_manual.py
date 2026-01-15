import asyncio
import os
import sys
from decimal import Decimal

# Add path to backend
sys.path.append(os.path.join(os.getcwd(), "backend"))

from core.mt5_executor import MT5Executor
from config import load_config
import logging

logging.basicConfig(level=logging.DEBUG)

async def test_mt5_login():
    # Use provided credentials
    login = 297413266
    server = "Exness-MT5Trial9"
    password = "S@jasper&12345"
    
    print(f"--- MT5 Login Test ---")
    print(f"Login: {login}")
    print(f"Server: {server}")
    
    # Load config for MT5 path
    config = load_config()
    executor = MT5Executor(mt5_path=config.mt5.mt5_path)
    
    print("Connecting...")
    success = await executor.connect(login, password, server)
    
    if success:
        print("SUCCESS: Connected to MT5!")
        
        # Get account info
        account_info = executor.get_account_info()
        if account_info:
            print(f"Account Balance: {account_info.get('balance')}")
            print(f"Account Equity: {account_info.get('equity')}")
            print(f"Broker: {account_info.get('company')}")
        
        # Try to get current price for Gold
        symbol = "XAUUSDm"
        price_info = executor.get_current_price(symbol)
        if price_info:
            print(f"Current {symbol} Ask: {price_info['ask']}, Bid: {price_info['bid']}")
            
            # Try a test order (tiny volume)
            print(f"Attempting test BUY order for {symbol}...")
            order_result = await executor.execute_market_order(
                symbol=symbol,
                side="buy",
                volume=Decimal("0.01"),
                comment="Credentials verification test"
            )
            
            if order_result.get("success"):
                print(f"SUCCESS: Order executed! Ticket: {order_result.get('ticket')}")
            else:
                print(f"FAILURE: Order failed: {order_result.get('error')}")
        else:
            print(f"Could not get price for {symbol}")
            
        executor.disconnect()
    else:
        print("FAILURE: Could not connect to MT5.")

if __name__ == "__main__":
    asyncio.run(test_mt5_login())
