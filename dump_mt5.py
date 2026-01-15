import MetaTrader5 as mt5
import sys

# Redirect stdout to a file to avoid truncation
with open("mt5_all_attrs.txt", "w") as f:
    for attr in sorted(dir(mt5)):
        try:
            val = getattr(mt5, attr)
            f.write(f"{attr}: {val}\n")
        except:
            pass
