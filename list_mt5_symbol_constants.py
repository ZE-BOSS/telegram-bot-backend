import MetaTrader5 as mt5
print("MT5 Symbol Constants:")
for attr in dir(mt5):
    if attr.startswith("SYMBOL"):
        print(f"{attr}: {getattr(mt5, attr)}")
