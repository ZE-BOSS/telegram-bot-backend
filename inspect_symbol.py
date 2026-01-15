import asyncio
import os
import sys

# Add path to backend
sys.path.append(os.path.join(os.getcwd(), "backend"))

from core.mt5_executor import MT5Executor
from config import load_config

async def inspect_symbol():
    login = 297413266
    server = "Exness-MT5Trial9"
    password = "S@jasper&12345"
    
    config = load_config()
    executor = MT5Executor(mt5_path=config.mt5.mt5_path)
    
    if await executor.connect(login, password, server):
        import MetaTrader5 as mt5
        symbol = "XAUUSDm"
        info = mt5.symbol_info(symbol)
        if info:
            print(f"Attributes for {symbol}:")
            for attr in dir(info):
                if not attr.startswith("_"):
                    try:
                        val = getattr(info, attr)
                        print(f"{attr}: {val}")
                    except:
                        pass
        executor.disconnect()
    else:
        print("Failed to connect.")

if __name__ == "__main__":
    asyncio.run(inspect_symbol())
