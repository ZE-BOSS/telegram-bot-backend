import asyncio
import os
import sys

# Add path to backend
sys.path.append(os.path.join(os.getcwd(), "backend"))

from core.mt5_executor import MT5Executor
from config import load_config

async def list_symbols():
    login = 297413266
    server = "Exness-MT5Trial9"
    password = "S@jasper&12345"
    
    config = load_config()
    executor = MT5Executor(mt5_path=config.mt5.mt5_path)
    
    if await executor.connect(login, password, server):
        import MetaTrader5 as mt5
        symbols = mt5.symbols_get()
        print(f"Total symbols found: {len(symbols)}")
        
        # Look for gold
        gold_symbols = [s.name for s in symbols if "XAU" in s.name or "GOLD" in s.name]
        print(f"Potential Gold symbols: {gold_symbols}")
        
        # Print first 10 for sample
        print("First 10 symbols:")
        for s in symbols[:10]:
            print(f"- {s.name}")
            
        executor.disconnect()
    else:
        print("Failed to connect.")

if __name__ == "__main__":
    asyncio.run(list_symbols())
