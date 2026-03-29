"""Run the dashboard: python -m src.dashboard"""

import uvicorn
from src.dashboard.app import app


def main():
    print("\n  Polymarket AI Trader Dashboard")
    print("  ==============================")
    print("  Open in browser: http://localhost:8888\n")
    uvicorn.run(app, host="0.0.0.0", port=8888, log_level="info")


if __name__ == "__main__":
    main()
