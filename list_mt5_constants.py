import MetaTrader5 as mt5
print("MT5 Constants:")
for attr in dir(mt5):
    if "FILLING" in attr:
        print(f"{attr}: {getattr(mt5, attr)}")
