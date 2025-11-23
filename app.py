from datetime import date, datetime, timedelta
import calendar

from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_

app = Flask(__name__)

# SQLite を使ったローカル保存設定
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///kakeibo.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


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
    day_of_month = db.Column(db.Integer, nullable=False)  # 1〜31
    amount = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    start_date = db.Column(db.Date, nullable=False)  # ここから有効
    end_date = db.Column(db.Date, nullable=True)     # ここまで（Noneなら無期限）


with app.app_context():
    db.create_all()


# 指定日付に有効な繰り返し支出を返す
def get_recurring_for_date(d: date):
    recs = MonthlyRecurring.query.all()
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
    today = date.today()
    return redirect(url_for("month_view", year=today.year, month=today.month))


# 月表示
from sqlalchemy import or_  # ← ファイルの先頭の import 群に追加しておく

@app.route("/month")
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
    transactions = Transaction.query.filter(
        Transaction.date >= start,
        Transaction.date <= end
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

# 日表示
@app.route("/day/<string:date_str>", methods=["GET", "POST"])
def day_view(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d").date()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        amount_str = request.form.get("amount", "").strip()
        kind = request.form.get("kind")  # "expense" or "income"

        # 入力チェック（空 or 数字以外なら何も保存せずその日へ戻る）
        if (not title) or (not amount_str) or (not amount_str.isdecimal()) or kind not in ("expense", "income"):
            return redirect(url_for("day_view", date_str=date_str))

        amount = int(amount_str)
        is_expense = (kind == "expense")

        t = Transaction(date=d, amount=amount, is_expense=is_expense, title=title)
        db.session.add(t)
        db.session.commit()

        return redirect(url_for("day_view", date_str=date_str))

    # ↓ここから下は今まで通りでOK（GET用）
    transactions = Transaction.query.filter_by(date=d).order_by(Transaction.id.desc()).all()
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

# 週表示（start=YYYY-MM-DD）
@app.route("/week")
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

    transactions = Transaction.query.filter(
        Transaction.date >= days[0],
        Transaction.date <= days[-1]
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


# 繰り返し支出の一覧・追加
@app.route("/recurring", methods=["GET", "POST"])
def recurring_view():
    if request.method == "POST":
        title = request.form.get("title")
        amount = request.form.get("amount", type=int)
        day_of_month = request.form.get("day_of_month", type=int)
        start_str = request.form.get("start_date")
        end_str = request.form.get("end_date")

        if title and amount and day_of_month:
            start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_str, "%Y-%m-%d").date() if end_str else None
            r = MonthlyRecurring(
                title=title,
                amount=amount,
                day_of_month=day_of_month,
                start_date=start_date,
                end_date=end_date
            )
            db.session.add(r)
            db.session.commit()

        return redirect(url_for("recurring_view"))

    recs = MonthlyRecurring.query.order_by(MonthlyRecurring.day_of_month).all()
    return render_template("recurring.html", recs=recs)

from flask import request  # まだ無ければ、ファイルの先頭の import 群に追加

# 単発の収支削除
@app.route("/delete/<int:id>")
def delete_transaction(id):
    t = Transaction.query.get(id)
    if t:
        db.session.delete(t)
        db.session.commit()
    return redirect(request.referrer or url_for("index"))


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
