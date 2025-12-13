from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sqlite3
import hashlib
import random
import uvicorn
from datetime import datetime, timedelta

# Инициализация приложения (ТОЛЬКО ОДИН РАЗ!)
app = FastAPI(
    title="🎌 Shinobi Casino: Village Legacy",
    description="Игровая вселенная с системой заработка",
    version="2.0.0"
)

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Модели данных
class UserCreate(BaseModel):
    username: str
    password: str
    village: str = "konoha"

class GameRequest(BaseModel):
    username: str
    bet: int
    element: Optional[str] = None

class DailyReward(BaseModel):
    username: str


# База данных
class Database:
    def __init__(self):
        self.init_database()

    def init_database(self):
        conn = sqlite3.connect("shinobi_casino.db")
        cursor = conn.cursor()

        # Пользователи
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                village TEXT DEFAULT 'konoha',
                ryo INTEGER DEFAULT 1000,
                rank TEXT DEFAULT 'genin',
                last_daily_reward TIMESTAMP,
                total_earned INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # История игр
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS game_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                game_type TEXT,
                bet_amount INTEGER,
                win_amount INTEGER,
                result TEXT,
                played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Ежедневные награды
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                reward_amount INTEGER,
                claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Миссии
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS missions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                mission_type TEXT,
                progress INTEGER DEFAULT 0,
                completed BOOLEAN DEFAULT 0,
                reward INTEGER
            )
        ''')

        conn.commit()
        conn.close()
        print("✅ База данных инициализирована")

    def get_connection(self):
        return sqlite3.connect("shinobi_casino.db")

    def create_user(self, username: str, password_hash: str, village: str):
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                INSERT INTO users (username, password_hash, village, ryo)
                VALUES (?, ?, ?, 1000)
            ''', (username, password_hash, village))
            user_id = cursor.lastrowid

            # Создаем начальные миссии
            missions = [
                (user_id, 'play_10_games', 0, 0, 500),
                (user_id, 'earn_5000_ryo', 0, 0, 1000),
                (user_id, 'reach_chunin', 0, 0, 2000)
            ]
            cursor.executemany('''
                INSERT INTO missions (user_id, mission_type, progress, completed, reward)
                VALUES (?, ?, ?, ?, ?)
            ''', missions)

            conn.commit()
            return user_id
        except sqlite3.IntegrityError:
            return None
        finally:
            conn.close()

    def get_user(self, username: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        conn.close()
        return user

    def update_balance(self, user_id: int, amount: int):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET ryo = ryo + ? WHERE id = ?', (amount, user_id))
        cursor.execute('UPDATE users SET total_earned = total_earned + ? WHERE id = ? AND ? > 0',
                       (amount, user_id, amount))
        conn.commit()
        conn.close()

    def add_game_record(self, user_id: int, game_type: str, bet: int, win: int, result: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO game_history (user_id, game_type, bet_amount, win_amount, result)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, game_type, bet, win, result))

        # Обновляем миссии
        cursor.execute('''
            UPDATE missions 
            SET progress = progress + 1 
            WHERE user_id = ? AND mission_type = 'play_10_games' AND completed = 0
        ''', (user_id,))

        conn.commit()
        conn.close()

    def check_daily_reward(self, user_id: int):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT last_daily_reward FROM users WHERE id = ?', (user_id,))
        result = cursor.fetchone()

        if not result or not result[0]:
            return True

        last_reward = datetime.fromisoformat(result[0])
        now = datetime.now()

        # Можно получить награду если прошло больше 24 часов
        can_claim = (now - last_reward) >= timedelta(hours=24)
        conn.close()
        return can_claim

    def give_daily_reward(self, user_id: int, amount: int):
        conn = self.get_connection()
        cursor = conn.cursor()

        # Даем награду
        cursor.execute('UPDATE users SET ryo = ryo + ? WHERE id = ?', (amount, user_id))
        cursor.execute('UPDATE users SET last_daily_reward = ? WHERE id = ?',
                       (datetime.now().isoformat(), user_id))

        # Записываем в историю
        cursor.execute('''
            INSERT INTO daily_rewards (user_id, reward_amount)
            VALUES (?, ?)
        ''', (user_id, amount))

        conn.commit()
        conn.close()

    def get_missions(self, user_id: int):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM missions WHERE user_id = ?', (user_id,))
        missions = cursor.fetchall()
        conn.close()
        return missions

    def update_mission(self, mission_id: int, progress: int):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE missions SET progress = ? WHERE id = ?', (progress, mission_id))

        # Проверяем выполнение
        cursor.execute('SELECT * FROM missions WHERE id = ?', (mission_id,))
        mission = cursor.fetchone()

        if mission and mission[3] >= mission[5]:  # progress >= reward
            cursor.execute('UPDATE missions SET completed = 1 WHERE id = ?', (mission_id,))

        conn.commit()
        conn.close()

    def get_leaderboard(self, limit: int = 10):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT username, village, ryo, rank, total_earned 
            FROM users 
            ORDER BY ryo DESC 
            LIMIT ?
        ''', (limit,))
        leaderboard = cursor.fetchall()
        conn.close()
        return leaderboard

# Инициализация
db = Database()


# Вспомогательные функции
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def calculate_rank(ryo: int) -> str:
    if ryo >= 1000000:
        return 'kage'
    elif ryo >= 100000:
        return 'jonin'
    elif ryo >= 10000:
        return 'chunin'
    else:
        return 'genin'


# Система игр
class GameSystem:
    @staticmethod
    def play_roulette(bet_element: str, bet_amount: int, village: str) -> dict:
        """Улучшенная рулетка - всегда есть шанс выиграть"""
        elements = ['fire', 'water', 'wind', 'earth', 'lightning']
        winning_element = random.choice(elements)

        # Базовый шанс выигрыша 60%
        if random.random() < 0.6:
            multiplier = 1.5

            # Бонус за свою стихию
            village_elements = {
                'konoha': 'fire',
                'suna': 'wind',
                'kiri': 'water',
                'iwa': 'earth'
            }

            if village in village_elements and winning_element == village_elements[village]:
                multiplier = 2.0

            win_amount = int(bet_amount * multiplier)
            result = 'win'
        else:
            win_amount = 0
            result = 'lose'

        return {
            'winning_element': winning_element,
            'win_amount': win_amount,
            'result': result,
            'details': f"Выпал: {winning_element}"
        }

    @staticmethod
    def play_slots(bet_amount: int, village: str) -> dict:
        """Слоты с гарантированным мини-выигрышем"""
        symbols = ['🍥', '🍃', '🌀', '💧', '🌍', '⚡', '🎯', '💰']

        # Генерируем результаты
        results = [random.choice(symbols) for _ in range(3)]

        # Гарантированный минимальный выигрыш 20%
        base_win = int(bet_amount * 0.2)

        # Проверяем комбинации
        win_amount = base_win

        if results[0] == results[1] == results[2]:
            # Джекпот - три одинаковых
            win_amount = bet_amount * 10
        elif results[0] == results[1] or results[1] == results[2]:
            # Два одинаковых
            win_amount = bet_amount * 3

        # Бонус деревни Суна
        if village == 'suna':
            win_amount = int(win_amount * 1.3)

        return {
            'results': results,
            'win_amount': win_amount,
            'result': 'win' if win_amount > 0 else 'lose'
        }

    @staticmethod
    def play_dice(bet_amount: int, village: str) -> dict:
        """Улучшенные кости - понятная логика"""
        dice_faces = ['⚀', '⚁', '⚂', '⚃', '⚄', '⚅']

        # Бросаем два кубика
        dice1 = random.randint(1, 6)
        dice2 = random.randint(1, 6)

        total = dice1 + dice2

        # Понятная система выигрыша:
        if total == 7:  # Самый частый результат
            win_amount = bet_amount * 2
        elif total in [6, 8]:
            win_amount = bet_amount * 1.5
        elif total in [2, 12]:  # Реже всего
            win_amount = bet_amount * 5
        else:
            win_amount = 0

        # Бонус деревни Ива
        if village == 'iwa' and win_amount > 0:
            win_amount = int(win_amount * 1.5)

        return {
            'dice1': dice_faces[dice1 - 1],
            'dice2': dice_faces[dice2 - 1],
            'total': total,
            'win_amount': int(win_amount),
            'result': 'win' if win_amount > 0 else 'lose'
        }

    @staticmethod
    def play_blackjack(bet_amount: int, village: str) -> dict:
        """Упрощенный блэкджек"""
        player_score = random.randint(15, 21)
        dealer_score = random.randint(15, 21)

        if player_score > 21:
            player_score = random.randint(15, 20)

        if dealer_score > 21:
            dealer_score = random.randint(15, 20)

        # Определяем победителя
        if player_score > dealer_score:
            win_amount = bet_amount * 2
            result = 'win'
        elif player_score == dealer_score:
            win_amount = bet_amount  # Возврат ставки
            result = 'draw'
        else:
            win_amount = 0
            result = 'lose'

        # Бонус деревни Кири
        if village == 'kiri' and win_amount > 0:
            win_amount = int(win_amount * 1.3)

        return {
            'player_score': player_score,
            'dealer_score': dealer_score,
            'win_amount': int(win_amount),
            'result': result
        }


# Инициализация системы игр
game_system = GameSystem()


# API эндпоинты
@app.get("/")
def home():
    return {
        "message": "🎌 Добро пожаловать в Shinobi Casino 2.0!",
        "features": [
            "✅ Система ежедневных наград",
            "✅ Миссии и достижения",
            "✅ Улучшенные игры с понятными правилами",
            "✅ Возможность заработка Рё"
        ]
    }


@app.post("/api/register")
def register(user: UserCreate):
    user_id = db.create_user(user.username, hash_password(user.password), user.village)

    if not user_id:
        raise HTTPException(status_code=400, detail="Пользователь уже существует")

    return {
        "success": True,
        "message": "Регистрация успешна! Получено 1000 Рё",
        "user": {
            "username": user.username,
            "village": user.village,
            "ryo": 1000,
            "rank": "genin"
        }
    }


@app.post("/api/login")
def login(username: str, password: str):
    user = db.get_user(username)

    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if user[2] != hash_password(password):
        raise HTTPException(status_code=401, detail="Неверный пароль")

    return {
        "success": True,
        "user": {
            "id": user[0],
            "username": user[1],
            "village": user[3],
            "ryo": user[4],
            "rank": user[5],
            "total_earned": user[7]
        }
    }


@app.get("/api/daily-reward/{username}")
def check_daily_reward(username: str):
    user = db.get_user(username)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    can_claim = db.check_daily_reward(user[0])
    return {
        "success": True,
        "can_claim": can_claim,
        "reward_amount": 500  # Ежедневная награда 500 Рё
    }


@app.post("/api/claim-daily-reward")
def claim_daily_reward(reward: DailyReward):
    user = db.get_user(reward.username)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    can_claim = db.check_daily_reward(user[0])
    if not can_claim:
        raise HTTPException(status_code=400, detail="Награду можно получать раз в 24 часа")

    reward_amount = 500
    db.give_daily_reward(user[0], reward_amount)

    # Обновляем баланс пользователя
    db.update_balance(user[0], reward_amount)

    return {
        "success": True,
        "message": f"Получена ежедневная награда: {reward_amount} Рё!",
        "new_balance": user[4] + reward_amount
    }


@app.post("/api/game/roulette")
def play_roulette(game: GameRequest):
    user = db.get_user(game.username)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if user[4] < game.bet:
        raise HTTPException(status_code=400, detail="Недостаточно Рё")

    # Играем
    result = game_system.play_roulette(game.element or "fire", game.bet, user[3])

    # Обновляем баланс
    new_balance = user[4] - game.bet + result['win_amount']
    db.update_balance(user[0], result['win_amount'] - game.bet)

    # Обновляем ранг
    new_rank = calculate_rank(new_balance)
    if new_rank != user[5]:
        # Обновляем в базе
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET rank = ? WHERE id = ?', (new_rank, user[0]))
        conn.commit()
        conn.close()

    # Записываем игру
    db.add_game_record(user[0], "roulette", game.bet, result['win_amount'], result['result'])

    return {
        "success": True,
        "game": "roulette",
        "result": result,
        "user": {
            "username": user[1],
            "new_balance": new_balance,
            "new_rank": new_rank
        }
    }


@app.post("/api/game/slots")
def play_slots(game: GameRequest):
    user = db.get_user(game.username)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if user[4] < game.bet:
        raise HTTPException(status_code=400, detail="Недостаточно Рё")

    result = game_system.play_slots(game.bet, user[3])

    new_balance = user[4] - game.bet + result['win_amount']
    db.update_balance(user[0], result['win_amount'] - game.bet)
    db.add_game_record(user[0], "slots", game.bet, result['win_amount'], result['result'])

    return {
        "success": True,
        "game": "slots",
        "result": result,
        "user": {
            "username": user[1],
            "new_balance": new_balance,
            "new_rank": calculate_rank(new_balance)
        }
    }


@app.post("/api/game/dice")
def play_dice(game: GameRequest):
    user = db.get_user(game.username)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if user[4] < game.bet:
        raise HTTPException(status_code=400, detail="Недостаточно Рё")

    result = game_system.play_dice(game.bet, user[3])

    new_balance = user[4] - game.bet + result['win_amount']
    db.update_balance(user[0], result['win_amount'] - game.bet)
    db.add_game_record(user[0], "dice", game.bet, result['win_amount'], result['result'])

    return {
        "success": True,
        "game": "dice",
        "result": result,
        "user": {
            "username": user[1],
            "new_balance": new_balance,
            "new_rank": calculate_rank(new_balance)
        }
    }


@app.post("/api/game/blackjack")
def play_blackjack(game: GameRequest):
    user = db.get_user(game.username)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if user[4] < game.bet:
        raise HTTPException(status_code=400, detail="Недостаточно Рё")

    result = game_system.play_blackjack(game.bet, user[3])

    new_balance = user[4] - game.bet + result['win_amount']
    db.update_balance(user[0], result['win_amount'] - game.bet)
    db.add_game_record(user[0], "blackjack", game.bet, result['win_amount'], result['result'])

    return {
        "success": True,
        "game": "blackjack",
        "result": result,
        "user": {
            "username": user[1],
            "new_balance": new_balance,
            "new_rank": calculate_rank(new_balance)
        }
    }


@app.get("/api/missions/{username}")
def get_missions(username: str):
    user = db.get_user(username)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    missions = db.get_missions(user[0])

    mission_list = []
    for mission in missions:
        mission_list.append({
            "id": mission[0],
            "type": mission[2],
            "progress": mission[3],
            "completed": bool(mission[4]),
            "reward": mission[5]
        })

    return {
        "success": True,
        "missions": mission_list
    }


@app.get("/api/leaderboard")
def get_leaderboard(limit: int = 10):
    leaderboard = db.get_leaderboard(limit)

    result = []
    for i, player in enumerate(leaderboard, 1):
        result.append({
            "rank": i,
            "username": player[0],
            "village": player[1],
            "ryo": player[2],
            "rank_title": player[3],
            "total_earned": player[4]
        })

    return {
        "success": True,
        "leaderboard": result
    }


@app.get("/api/stats/{username}")
def get_stats(username: str):
    user = db.get_user(username)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*), SUM(bet_amount), SUM(win_amount) FROM game_history WHERE user_id = ?', (user[0],))
    stats = cursor.fetchone()
    conn.close()

    return {
        "success": True,
        "stats": {
            "total_games": stats[0] or 0,
            "total_bet": stats[1] or 0,
            "total_win": stats[2] or 0,
            "total_earned": user[7] or 0,
            "profit": (stats[2] or 0) - (stats[1] or 0)
        }
    }

# Запуск сервера
if __name__ == "__main__":
    print("=" * 50)
    print("🎌  Shinobi Casino 2.0 запускается...")
    print("✨  Новые функции:")
    print("   ✅ Система ежедневных наград")
    print("   ✅ Миссии и достижения")
    print("   ✅ Возможность заработка Рё")
    print("🌐  Документация API: http://localhost:8000/docs")
    print("🎮  Фронтенд: frontend/index.html")
    print("=" * 50)

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)