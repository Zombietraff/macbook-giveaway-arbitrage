import hmac
import hashlib
import urllib.parse
from aiohttp import web
import json
import logging
from config import BOT_TOKEN
from db.database import get_db
from db.models import get_user, has_user_flag, set_user_flag
import random

logger = logging.getLogger(__name__)
_WEBAPP_DISCLAIMER_FLAG = "webapp_disclaimer_accepted"

def validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """Validate Telegram Web Apps initData."""
    try:
        parsed_data = dict(urllib.parse.parse_qsl(init_data))
        if 'hash' not in parsed_data:
            return None
            
        hash_val = parsed_data.pop('hash')
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed_data.items())
        )
        
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        if calculated_hash != hash_val:
            return None
            
        user_data = json.loads(parsed_data.get("user", "{}"))
        return user_data
    except Exception as e:
        logger.error(f"Error validating initData: {e}")
        return None

def webapp_auth(func):
    """Decorator to enforce Telegram Web App authentication."""
    async def wrapper(request: web.Request):
        auth_header = request.headers.get("Authorization", "")
        init_data = ""
        if auth_header.startswith("tma "):
            init_data = auth_header[4:].strip()
        if not init_data:
            init_data = request.headers.get("X-Telegram-Init-Data", "").strip()

        if not init_data:
            return web.json_response({"error": "Unauthorized"}, status=401)
            
        user_data = validate_init_data(init_data, BOT_TOKEN)
        if not user_data:
            return web.json_response({"error": "Forbidden: Invalid signature"}, status=403)
            
        request["tg_user"] = user_data
        return await func(request)
    return wrapper

# Let's map emojis to React frontend strings
SYMBOL_MAP = {
    "CHERRY": 0.5,
    "APPLE": 0.3,
    "BANANA": 0.15,
    "BAR": 0.05,
}

def generate_spin_result() -> list[str]:
    # Randomly select 3 symbols
    # A realistic slot machine might use reels, but we can do a simple weighted random here for the demo.
    symbols = list(SYMBOL_MAP.keys())
    weights = list(SYMBOL_MAP.values())
    return random.choices(symbols, weights=weights, k=3)

def calculate_spin_multiplier(symbols: list[str]) -> float:
    # 3 of a kind
    if symbols[0] == symbols[1] == symbols[2]:
        if symbols[0] == "BAR":
            return 5.0
        elif symbols[0] == "BANANA":
            return 4.0
        elif symbols[0] == "APPLE":
            return 3.0
        elif symbols[0] == "CHERRY":
            return 2.0
    # 2 of a kind
    if symbols[0] == symbols[1] or symbols[1] == symbols[2] or symbols[0] == symbols[2]:
        return 0.5
    return 0.0

@webapp_auth
async def get_user_balance(request: web.Request):
    tg_user = request["tg_user"]
    user_id = tg_user.get("id")
    
    user = await get_user(user_id)
    if not user:
        return web.json_response({"error": "User not found"}, status=404)
        
    language_code = user["language_code"] if user["language_code"] in {"ru", "uk"} else "ru"
    disclaimer_accepted = await has_user_flag(user_id, _WEBAPP_DISCLAIMER_FLAG)
        
    return web.json_response({
        "coins": user["tickets"],
        "languageCode": language_code,
        "disclaimerAccepted": disclaimer_accepted,
    })

@webapp_auth
async def accept_disclaimer(request: web.Request):
    tg_user = request["tg_user"]
    user_id = tg_user.get("id")
    
    user = await get_user(user_id)
    if not user:
        return web.json_response({"error": "User not found"}, status=404)
        
    await set_user_flag(user_id, _WEBAPP_DISCLAIMER_FLAG)
    return web.json_response({"disclaimerAccepted": True})

@webapp_auth
async def spin_slot(request: web.Request):
    tg_user = request["tg_user"]
    user_id = tg_user.get("id")
    
    try:
        body = await request.json()
        bet_amount = int(body.get("bet", 0))
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON"}, status=400)
        
    if bet_amount <= 0:
        return web.json_response({"error": "Invalid bet amount"}, status=400)

    if not await has_user_flag(user_id, _WEBAPP_DISCLAIMER_FLAG):
        return web.json_response({"error": "Disclaimer required"}, status=403)
        
    # Validation against limits and balance should be done here, ensuring atomic transaction
    # Since we want atomic, we should duplicate or reuse `play_casino_spin_atomic` differently
    # because it currently uses dice result. Let's write a new atomic method for WebApp spin.
    
    # Custom atomic spin for the web app
    # Check minimum balance? The React app might let users bet any amount up to max.
    # The current bot rules require a minimum of 1 ticket remaining. 
    # For now, let's just make sure they have balance (tickets).
    
    db = await get_db()
    async with db.execute("BEGIN IMMEDIATE"):
        try:
            cursor = await db.execute("SELECT tickets FROM users WHERE id = ?", (user_id,))
            row = await cursor.fetchone()
            if not row:
                raise ValueError("User not found")
                
            current_tickets = row["tickets"]
            if current_tickets < bet_amount: # For webapp we might not require 1 ticket remaining, let's keep it simple
                raise ValueError("Insufficient balance")
                
            # deduct bet
            await db.execute("UPDATE users SET tickets = tickets - ? WHERE id = ?", (bet_amount, user_id))
            
            # Spin math
            symbols = generate_spin_result()
            multiplier = calculate_spin_multiplier(symbols)
            win_amount = int(bet_amount * multiplier)
            
            result_type = 'win' if multiplier >= 3.0 else ('jackpot' if multiplier == 5.0 else 'loss')
            
            # add win
            if win_amount > 0:
                await db.execute("UPDATE users SET tickets = tickets + ? WHERE id = ?", (win_amount, user_id))
            
            final_balance = current_tickets - bet_amount + win_amount
                
            # Log spin (this assumes the casino_spins table exists over in models.py which we know it does)
            await db.execute(
                "INSERT INTO casino_spins (user_id, bet_amount, dice_value, result_type, multiplier, balance_before, balance_after) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, bet_amount, 0, result_type, multiplier, current_tickets, final_balance)
            )
            
            await db.commit()
            
            return web.json_response({
                "symbols": symbols,
                "win": win_amount,
                "coins": final_balance,
                "multiplier": multiplier
            })
            
        except Exception as e:
            await db.rollback()
            logger.error(f"Spin error: {e}")
            return web.json_response({"error": str(e)}, status=400)


def setup_routes(app: web.Application):
    # Simple CORS middleware
    @web.middleware
    async def cors_middleware(request, handler):
        if request.method == "OPTIONS":
            return web.Response(
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Authorization, X-Telegram-Init-Data, Content-Type",
                }
            )
        response = await handler(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, X-Telegram-Init-Data, Content-Type"
        return response

    app.middlewares.append(cors_middleware)
    
    app.router.add_get("/api/user", get_user_balance)
    app.router.add_post("/api/disclaimer/accept", accept_disclaimer)
    app.router.add_post("/api/spin", spin_slot)
