# Giveaway WebApp

Telegram mini app used by the giveaway bot.

The user-facing interface is localized through the bot user profile language (`users.language_code`) and uses the backend WebApp API for balance, spins, and the entertainment disclaimer.

## Local Development

```bash
npm run dev
```

The Vite dev server proxies `/api/*` to the Python bot API on `127.0.0.1:8080`.

## Build

```bash
npm run build
```

## License

This vendored frontend keeps the original license files in the repository.
