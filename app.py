from datetime import date, datetime, timedelta
import calendar

from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

# SQLite を使ったローカル保存設定
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///kakeibo.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
db = SQLAlchemy(app)


# ユーザー情報（ログイン用）
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# 単発の収支
class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Integer, nullable=False)  # 円
    is_expense = db.Column(db.Boolean, nullable=False)  # True=支出, False=収入
    title = db.Column(db.String(200), nullable=False)

    def sign_amount(self):
        return -self.amount if self.is_expense else self.amount


# 毎月の繰り返し支出（毎月◯日のみ）
class MonthlyRecurring(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)  # ★追加
    day_of_month = db.Column(db.Integer, nullable=False)  # 1〜31
    amount = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)

with app.app_context():
    db.create_all()

def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)
    return wrapped_view

# 指定日付に有効な繰り返し支出を返す
def get_recurring_for_date(d: date):
    user_id = session.get("user_id")
    if user_id is None:
        return []

    recs = MonthlyRecurring.query.filter_by(user_id=user_id).all()
    result = []
    for r in recs:
        if r.day_of_month != d.day:
            continue
        if d < r.start_date:
            continue
        if r.end_date and d > r.end_date:
            continue
        result.append(r)
    return result


# トップ → 今月のカレンダーへ
@app.route("/")
def index():
    if "user_id" not in session:
        return redirect(url_for("login"))
    today = date.today()
    return redirect(url_for("month_view", year=today.year, month=today.month))

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    username = db.Column(db.String(50), nullable=False)  # ★追加
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


        if not email or not password:
            return "メールアドレスとパスワードを入力してください。"

        # すでに登録済みかチェック
        existing = User.query.filter_by(email=email).first()
        if existing:
            return "そのメールアドレスは既に登録されています。"

        # パスワードをハッシュ化
        password_hash = generate_password_hash(password)

        user = User(email=email, password_hash=password_hash)
        db.session.add(user)
        db.session.commit()

        return redirect(url_for("login"))

    # GET のとき
    return """
    <h1>ユーザー登録</h1>
    <form method="post">
        <input type="email" name="email" placeholder="メールアドレス" required><br>
        <input type="password" name="password" placeholder="パスワード" required><br>
        <button type="submit">登録</button>
    </form>
    <p><a href="/login">ログインはこちら</a></p>
    """

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            # 認証成功 → セッションに保存
            session["user_id"] = user.id
            session["user_email"] = user.email
            return redirect(url_for("index"))  # ホームへ
        else:
            return "メールアドレスまたはパスワードが違います。"

    # GET のとき
    return """
    <h1>ログイン</h1>
    <form method="post">
        <input type="email" name="email" placeholder="メールアドレス" required><br>
        <input type="password" name="password" placeholder="パスワード" required><br>
        <button type="submit">ログイン</button>
    </form>
    <p><a href="/register">新規登録はこちら</a></p>
    """

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
def index():
    today = date.today()
    return redirect(url_for("month_view", year=today.year, month=today.month))

# 月表示
from sqlalchemy import or_  # ← ファイルの先頭の import 群に追加しておく

@app.route("/month")
@login_required
def month_view():
    year = request.args.get("year", type=int)
    month = request.args.get("month", type=int)

    if not year or not month:
        today = date.today()
        year, month = today.year, today.month

    # カレンダー用の日付リスト
    cal = calendar.Calendar(firstweekday=6)  # 日曜始まり
    month_dates = list(cal.itermonthdates(year, month))

    # この月の1日〜末日
    start = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    end = date(year, month, last_day)

    # ① 単発トランザクションをまとめて取得（クエリ1回）
    user_id = session["user_id"]

 transactions = Transaction.query.filter(
    Transaction.user_id == user_id,
    Transaction.date >= start,
    Transaction.date <= end,
 ).all()

 recurring_all = MonthlyRecurring.query.filter(
    MonthlyRecurring.user_id == user_id,
    MonthlyRecurring.start_date <= end,
    or_(MonthlyRecurring.end_date == None, MonthlyRecurring.end_date >= start),
 ).all()

    daily_totals = {}

    # 単発分を日別に合計
    for t in transactions:
        daily_totals.setdefault(t.date, 0)
        daily_totals[t.date] += t.sign_amount()

    # ② この月に関係する繰り返し支出をまとめて取得（クエリ1回）
    recurring_all = MonthlyRecurring.query.filter(
        MonthlyRecurring.start_date <= end,
        or_(MonthlyRecurring.end_date == None, MonthlyRecurring.end_date >= start)
    ).all()

    # 繰り返し支出を、該当する各日に足し込む
    for r in recurring_all:
        # この月に存在しうる日付だけを見る
        day = r.day_of_month
        if 1 <= day <= last_day:
            d = date(year, month, day)
            # start〜end の範囲に入っていることは filter で保証済み
            daily_totals.setdefault(d, 0)
            daily_totals[d] -= r.amount  # 支出なのでマイナス

    # 週ごとの2次元配列に整形（テンプレート用）
    weeks = []
    week = []
    for d in month_dates:
        if len(week) == 7:
            weeks.append(week)
            week = []
        week.append({
            "date": d,
            "in_month": (d.month == month),
            "total": daily_totals.get(d, 0),
        })
    if week:
        weeks.append(week)

    # 月全体の合計
    month_total = sum(
        daily_totals.get(date(year, month, day), 0)
        for day in range(1, last_day + 1)
    )

    return render_template(
        "month.html",
        year=year,
        month=month,
        weeks=weeks,
        month_total=month_total
    )

 @app.route("/month")
 @login_required
 def month_view():
    today = date.today()
    return redirect(url_for("month_view", year=today.year, month=today.month))

# 日表示
@app.route("/day/<string:date_str>", methods=["GET", "POST"])
@login_required
def day_view(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d").date()

        amount = int(amount_str)
     is_expense = (kind == "expense")

     t = Transaction(
        user_id=session["user_id"],  # ★追加
        date=d,
        amount=amount,
        is_expense=is_expense,
        title=title,
     )
     db.session.add(t)
     db.session.commit()


        return redirect(url_for("day_view", date_str=date_str))

    # ↓ここから下は今まで通りでOK（GET用）
   user_id = session["user_id"]

 transactions = Transaction.query.filter(
    Transaction.user_id == user_id,
    Transaction.date == d,
 ).order_by(Transaction.id.desc()).all()

    recurring = get_recurring_for_date(d)

    total = sum(t.sign_amount() for t in transactions)
    for r in recurring:
        total -= r.amount

    return render_template(
        "day.html",
        day=d,
        transactions=transactions,
        recurring=recurring,
        total=total
    )
 @app.route("/day/<string:date_str>", methods=["GET", "POST"])
 @login_required
 def day_view(date_str):
    today = date.today()
    return redirect(url_for("month_view", year=today.year, month=today.month))


# 週表示（start=YYYY-MM-DD）
@app.route("/week")
@login_required
def week_view():
    start_str = request.args.get("start")
    if start_str:
        start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
    else:
        today = date.today()
        weekday = today.weekday()  # 月曜=0
        # 日曜スタートの週
        start_date = today - timedelta(days=(weekday + 1) % 7)

    days = [start_date + timedelta(days=i) for i in range(7)]

    user_id = session["user_id"]

 transactions = Transaction.query.filter(
    Transaction.user_id == user_id,
    Transaction.date >= days[0],
    Transaction.date <= days[-1],
 ).all()



    by_date = {d: [] for d in days}
    for t in transactions:
        if t.date in by_date:
            by_date[t.date].append(t)

    week_info = []
    for d in days:
        trans = by_date[d]
        recs = get_recurring_for_date(d)
        total = sum(t.sign_amount() for t in trans) - sum(r.amount for r in recs)
        week_info.append({
            "date": d,
            "transactions": trans,
            "recurring": recs,
            "total": total
        })

    return render_template(
        "week.html",
        week_info=week_info,
        start_date=days[0],
        end_date=days[-1]
    )
 @app.route("/week")
 @login_required
 def week_view():
    today = date.today()
    return redirect(url_for("month_view", year=today.year, month=today.month))


# 繰り返し支出の一覧・追加
@app.route("/recurring", methods=["GET", "POST"])
@login_required
def recurring_view():

        if title and amount and day_of_month:
        start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_str, "%Y-%m-%d").date() if end_str else None
        r = MonthlyRecurring(
            user_id=session["user_id"],  # ★追加
            title=title,
            amount=amount,
            day_of_month=day_of_month,
            start_date=start_date,
            end_date=end_date,
         )
         db.session.add(r)
         db.session.commit()


        return redirect(url_for("recurring_view"))

    user_id = session["user_id"]
 recs = MonthlyRecurring.query.filter_by(user_id=user_id)\
    .order_by(MonthlyRecurring.day_of_month).all()

    return render_template("recurring.html", recs=recs)

from flask import request  # まだ無ければ、ファイルの先頭の import 群に追加

 @app.route("/recurring", methods=["GET", "POST"])
 @login_required
 def recurring_view():
     today = date.today()
    return redirect(url_for("month_view", year=today.year, month=today.month))

# 単発の収支削除
@app.route("/delete/<int:id>")
@login_required
def delete_transaction(id):
    user_id = session["user_id"]
    t = Transaction.query.filter_by(id=id, user_id=user_id).first()
    if t:
        db.session.delete(t)
        db.session.commit()
    return redirect( ... )  # 元のままでOK

# 繰り返し支出削除
@app.route("/delete_recurring/<int:id>")
def delete_recurring(id):
    r = MonthlyRecurring.query.get(id)
    if r:
        db.session.delete(r)
        db.session.commit()
    return redirect(url_for("recurring_view"))

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
 @app.route("/delete/<int:id>")
 @login_required
 def delete_transaction(id):
    today = date.today()
    return redirect(url_for("month_view", year=today.year, month=today.month))

