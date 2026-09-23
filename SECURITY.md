# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 1.x.x   | ✅                 |

## Reporting a Vulnerability

If you discover a security vulnerability, please follow these steps:

1. **Do not open a public issue.** This could expose other users to risk.
2. Email **shayanghad0@gmail.com** with the details.
3. Include the affected file(s), reproduction steps, and severity estimate.
4. You will receive a response within **72 hours**.
5. Once fixed, your name will be added to the acknowledgements section (optional).

## Known Security Considerations

This project connects directly to a live MetaTrader 5 brokerage account. Before running:

- **Never commit credentials.** API keys, broker tokens, and `.env` secrets are ignored by `.gitignore`.
- **Test on demo first.** All order placement is real-money — always verify on a demo account.
- **Review before trust.** Audit every order request in `order.py` and `trader.py` before running in production.
- **Emergency kill-switch.** Press `Ctrl+C` to detach; a broker-side TP/SL is set automatically.
- **P&L caps.** Hard limits (`MAX_PROFIT_USD` / `MAX_LOSS_USD`) act as a final safety net if broker TP/SL fails.

## Responsible Disclosure

Findings will be addressed promptly. High-severity issues affecting fund safety will be prioritised above all else.
