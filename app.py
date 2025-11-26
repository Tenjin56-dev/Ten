from datetime import date, datetime, timedelta
import calendar

from flask import Flask, render_template, request, redirect, url_for, session,abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

# SQLite を使ったローカル保存設定
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///kakeibo_v2.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
with app.app_context():
    db.create_all()


# ユーザー情報（ログイン用）
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    username = db.Column(db.String(50), nullable=False)  # ★これを必ず追加
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# 単発の収支
class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Integer, nullable=False)  # 円
    is_expense = db.Column(db.Boolean, nullable=False)  # True=支出, False=収入
    title = db.Column(db.String(200), nullable=False)
    # ★ 追加
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    def sign_amount(self):
        return -self.amount if self.is_expense else self.amount


# 毎月の繰り返し支出
class MonthlyRecurring(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    day_of_month = db.Column(db.Integer, nullable=False)  # 1〜31
    amount = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    # ★ 追加
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

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

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not email or not password or not username:
            return "メールアドレス・ユーザー名・パスワードを入力してください。"

        existing = User.query.filter_by(email=email).first()
        if existing:
            return "そのメールアドレスは既に登録されています。"

        password_hash = generate_password_hash(password)
        user = User(email=email, username=username, password_hash=password_hash)
        db.session.add(user)
        db.session.commit()

        return redirect(url_for("login"))

    return render_template("register.html")

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


# 月表示
from sqlalchemy import or_

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

    daily_totals = {}

    # ② 単発分を日別に合計
    for t in transactions:
        daily_totals.setdefault(t.date, 0)
        daily_totals[t.date] += t.sign_amount()

    # ③ この月に関係する繰り返し支出をまとめて取得（クエリ1回）
    recurring_all = MonthlyRecurring.query.filter(
        MonthlyRecurring.user_id == user_id,
        MonthlyRecurring.start_date <= end,
        or_(MonthlyRecurring.end_date == None, MonthlyRecurring.end_date >= start)
    ).all()

    # ④ 繰り返し支出を、該当する各日に足し込む
    for r in recurring_all:
        day = r.day_of_month
        if 1 <= day <= last_day:
            d = date(year, month, day)
            daily_totals.setdefault(d, 0)
            daily_totals[d] -= r.amount  # 支出なのでマイナス

    # （以下、weeks の計算と month_total の計算は元のままでOK）
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

    month_total = sum(
        daily_totals.get(date(year, month, day), 0)
        for day in range(1, last_day + 1)
    )

    return render_template(
        "month.html",
        year=year,
        month=month,
        weeks=weeks,
        month_total=month_total,
    )


# 日表示
@app.route("/day/<string:date_str>", methods=["GET", "POST"])
@login_required
def day_view(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d").date()

    # POST（新規登録）
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        amount_str = request.form.get("amount", "").strip()
        kind = request.form.get("kind")  # "expense" or "income"

        # 入力チェック
        if (not title) or (not amount_str) or (not amount_str.isdecimal()) \
                or kind not in ("expense", "income"):
            return redirect(url_for("day_view", date_str=date_str))

        amount = int(amount_str)
        is_expense = (kind == "expense")

        t = Transaction(
            user_id=session["user_id"],
            date=d,
            amount=amount,
            is_expense=is_expense,
            title=title,
        )
        db.session.add(t)
        db.session.commit()

        return redirect(url_for("day_view", date_str=date_str))

    # GET（表示）
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
        total=total,
    )

# 週表示 (start=YYYY-MM-DD)
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

    # この週7日分のリスト
    days = [start_date + timedelta(days=i) for i in range(7)]

    user_id = session["user_id"]

    # ユーザーの週次データを取得
    transactions = Transaction.query.filter(
        Transaction.user_id == user_id,
        Transaction.date >= days[0],
        Transaction.date <= days[-1],
    ).all()

    # 日付ごとに分類
    by_date = {d: [] for d in days}
    for t in transactions:
        if t.date in by_date:
            by_date[t.date].append(t)

    # テンプレートへ渡す情報を作成
    week_info = []
    for d in days:
        trans = by_date[d]
        recs = get_recurring_for_date(d)
        total = sum(t.sign_amount() for t in trans) - sum(r.amount for r in recs)
        week_info.append({
            "date": d,
            "transactions": trans,
            "recurring": recs,
            "total": total,
        })

    return render_template(
        "week.html",
        week_info=week_info,
        start_date=days[0],
        end_date=days[-1],
    )

# 繰り返し支出の一覧・追加
@app.route("/recurring", methods=["GET", "POST"])
@login_required
def recurring_view():
    if request.method == "POST":
        title = request.form.get("title")
        amount = request.form.get("amount", type=int)
        day_of_month = request.form.get("day_of_month", type=int)
        start_str = request.form.get("start_date")
        end_str = request.form.get("end_date")

        if title and amount and day_of_month:
            start_date = datetime.strptime(start_str, "%Y-%m-%d").date() if start_str else date.today()
            end_date = datetime.strptime(end_str, "%Y-%m-%d").date() if end_str else None

            r = MonthlyRecurring(
                user_id=session["user_id"],  # ★ユーザーごと
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
    recs = MonthlyRecurring.query.filter_by(user_id=user_id).order_by(
        MonthlyRecurring.day_of_month
    ).all()

    return render_template("recurring.html", recs=recs)


from flask import request  # まだ無ければ、ファイルの先頭の import 群に

# 単発の収支削除
@app.route("/delete/<int:id>")
@login_required
def delete_transaction(id):
    t = Transaction.query.get(id)
    if t:
        db.session.delete(t)
        db.session.commit()

    # 直前のページに戻る（無ければ month_view へ）
    return redirect(request.referrer or url_for("month_view"))

from flask import abort, render_template, request, redirect, url_for, session

@app.route("/username", methods=["GET", "POST"])
@login_required
def change_username():
    # 1. セッションに user_id が無ければログイン画面へ
    user_id = session.get("user_id")
    if not user_id:
        # 念のためセッションをクリアしてログインへ
        session.clear()
        return redirect(url_for("login"))

    # 2. DB からユーザーを取得
    user = User.query.get(user_id)

    # 3. もし該当ユーザーが見つからなければ、
    #    古いセッションだと考えてログインし直してもらう
    if user is None:
        session.clear()
        return redirect(url_for("login"))

    # ここまで来たら「本当に存在するログイン中ユーザー」

    if request.method == "POST":
        new_name = request.form.get("username", "").strip()

        if not new_name:
            error = "ユーザー名を入力してください。"
            return render_template(
                "username.html",
                current_username=user.username,
                error=error,
            )

        duplicate = User.query.filter(
            User.id != user.id,
            User.username == new_name,
        ).first()
        if duplicate:
            error = "そのユーザー名は既に使われています。"
            return render_template(
                "username.html",
                current_username=user.username,
                error=error,
            )

        user.username = new_name
        db.session.commit()

        return redirect(url_for("month_view"))

    # GET のとき
    return render_template(
        "username.html",
        current_username=user.username,
        error=None,
    )


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


