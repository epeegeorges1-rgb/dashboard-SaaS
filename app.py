from flask import Flask, render_template, request, redirect, url_for, session, send_file
import json, os, datetime
import pandas as pd
from io import BytesIO
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import plotly.express as px

app = Flask(__name__)
app.secret_key = "ton_secret_key"  # Change pour prod

# ------------------ FILE SETUP ------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

PROJECT_FILE = os.path.join(DATA_DIR, "projects.json")
USER_FILE = os.path.join(DATA_DIR, "users.json")

def load_json(file_path):
    if os.path.exists(file_path):
        try:
            with open(file_path,"r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []

def save_json(file_path, data):
    with open(file_path,"w") as f:
        json.dump(data, f, indent=4)

# ------------------ AUTH ------------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method=="POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        users = load_json(USER_FILE)
        if any(u["username"]==username for u in users):
            return "<p>Nom d'utilisateur déjà pris.</p><a href='/register'>Retour</a>"
        hashed_pw = generate_password_hash(password)
        users.append({"username": username, "password": hashed_pw})
        save_json(USER_FILE, users)
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        users = load_json(USER_FILE)
        user = next((u for u in users if u["username"]==username), None)
        if user and check_password_hash(user["password"], password):
            session["username"] = username
            return redirect(url_for("index"))
        return "<p>Identifiants incorrects.</p><a href='/login'>Retour</a>"
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("login"))

# ------------------ HELPERS ------------------
def compute_totals(project):
    totals={}
    for e in project["expenses"]:
        cat=e["category"]
        totals[cat]=totals.get(cat,0)+e["amount"]
    return totals

def compute_summary(project):
    totals = compute_totals(project)
    summary=[]
    for cat, budget in project.get("categories",{}).items():
        spent = totals.get(cat,0)
        remaining = budget - spent
        percent = (spent/budget*100) if budget>0 else 0
        summary.append({
            "category":cat,
            "budget":budget,
            "spent":spent,
            "remaining":remaining,
            "percent":round(percent,1)
        })
    return summary

def generate_alerts(summary):
    alerts=[]
    for s in summary:
        if s["percent"]>100:
            alerts.append(f"⚠️ Dépassement dans {s['category']}")
        elif s["percent"]>80:
            alerts.append(f"⚠️ Attention: {s['category']} presque atteint")
    return alerts

# ------------------ PROJECT ROUTES ------------------
@app.route("/")
@login_required
def index():
    projects = load_json(PROJECT_FILE)
    return render_template("index.html", projects=projects)

@app.route("/add_expense/<project_name>", methods=["POST"])
@login_required
def add_expense(project_name):
    data = load_json(PROJECT_FILE)
    project = next((p for p in data if p["name"] == project_name), None)

    if not project:
        return "Projet introuvable"

    title = request.form["title"]
    category = request.form["category"]
    amount = float(request.form["amount"])
    date = request.form.get("date", "")

    # ajouter catégorie si absente
    if category not in project["categories"]:
        project["categories"][category] = 0

    project["expenses"].append({
        "title": title,
        "category": category,
        "amount": amount,
        "date": date
    })

    save_json(PROJECT_FILE, data)

    return redirect(url_for("view_project", name=project_name, success=1))

@app.route("/project/<name>")
@login_required
def view_project(name):
    data = load_json(PROJECT_FILE)
    project = next((p for p in data if p["name"]==name), None)
    if not project:
        return f"<p>Projet '{name}' introuvable.</p><a href='/'>Retour</a>"
    summary = compute_summary(project)
    alerts = generate_alerts(summary)

    table_rows=[]
    for idx,e in enumerate(project["expenses"]):
        budget_cat = project["categories"].get(e["category"],0)
        spent = sum(exp["amount"] for exp in project["expenses"] if exp["category"]==e["category"])
        remaining = budget_cat - spent
        percent = (spent/budget_cat*100) if budget_cat>0 else 0
        table_rows.append({
            "index":idx,
            "title":e["title"],
            "category":e["category"],
            "amount":e["amount"],
            "budget":budget_cat,
            "remaining":remaining,
            "percent":round(percent,1),
            "date":e["date"]
        })
    return render_template("project.html", project=project, summary=summary, table_rows=table_rows, alerts=alerts)

# ------------------ EDIT / DELETE EXPENSE ------------------
@app.route("/edit_expense/<project_name>/<int:expense_index>", methods=["POST"])
@login_required
def edit_expense(project_name, expense_index):
    data = load_json(PROJECT_FILE)
    project = next((p for p in data if p["name"]==project_name), None)
    if not project: return "Projet introuvable"
    if not 0<=expense_index<len(project["expenses"]): return "Dépense introuvable"
    e = project["expenses"][expense_index]
    e["title"]=request.form["title"].strip()
    e["category"]=request.form["category"].strip()
    e["amount"]=float(request.form["amount"])
    new_budget=request.form.get("budget","").strip()
    try: new_budget=float(new_budget) if new_budget else 0
    except: new_budget=0
    if new_budget>0: project["categories"][e["category"]]=new_budget
    save_json(PROJECT_FILE,data)
    return redirect(url_for("view_project", name=project_name))

@app.route("/delete_expense/<project_name>/<int:expense_index>", methods=["POST"])
@login_required
def delete_expense(project_name, expense_index):
    data = load_json(PROJECT_FILE)
    project = next((p for p in data if p["name"]==project_name), None)
    if project and 0<=expense_index<len(project["expenses"]):
        del project["expenses"][expense_index]
        save_json(PROJECT_FILE,data)
    return redirect(url_for("view_project", name=project_name))

# ------------------ EXPORT EXCEL ------------------
@app.route("/export_excel/<project_name>")
@login_required
def export_excel(project_name):
    data = load_json(PROJECT_FILE)
    project = next((p for p in data if p["name"]==project_name), None)
    if not project: return f"<p>Projet '{project_name}' introuvable.</p><a href='/'>Retour</a>"
    df = pd.DataFrame(project["expenses"])
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Dépenses')
    output.seek(0)
    return send_file(output, download_name=f"{project_name}_expenses.xlsx", as_attachment=True)

# ------------------ CHARTS ------------------
@app.route("/chart/interactive/<name>")
@login_required
def chart_interactive(name):
    project = next((p for p in load_json(PROJECT_FILE) if p["name"]==name), None)
    if not project: return "<h3>Projet introuvable</h3>"
    summary = compute_summary(project)
    if not summary: return "<h3 style='text-align:center'>Ajoute des données pour voir le graphique</h3>"
    df=pd.DataFrame(summary)
    palette = px.colors.qualitative.Plotly
    color_map = {cat: palette[i % len(palette)] for i, cat in enumerate(df["category"])}
    df["color"]=df["category"].map(color_map)
    fig=px.pie(df,names="category",values="spent",color="category",
               color_discrete_map=color_map,
               title=f"Dépenses par catégorie - {project['name']}",
               custom_data=["spent","budget","remaining"])
    fig.update_traces(textposition='inside',textinfo='percent+label',
                      hovertemplate="<b>%{label}</b><br>Dépensé: %{customdata[0]}<br>Budget: %{customdata[1]}<br>Restant: %{customdata[2]}")
    return fig.to_html(full_html=False)

@app.route("/chart/budget_duration")
@login_required
def chart_budget_duration():
    data = load_json(PROJECT_FILE)
    if not data: return "<h3 style='text-align:center'>Aucun projet</h3>"
    projects_data=[]
    for p in data:
        try:
            start = datetime.datetime.strptime(p["start_date"],"%Y-%m-%d")
            end = datetime.datetime.strptime(p["end_date"],"%Y-%m-%d")
            duration_days=(end-start).days
            if duration_days<=0: duration_days=1
        except: duration_days=1
        budget_per_day = p["budget"]/duration_days
        projects_data.append({
            "Projet":p["name"],
            "Budget total":p["budget"],
            "Durée (jours)":duration_days,
            "Budget / jour":round(budget_per_day,2)
        })
    df=pd.DataFrame(projects_data)
    fig=px.bar(df,x="Projet",y="Budget / jour",color="Durée (jours)",
               text="Durée (jours)",title="Budget par jour selon la durée des projets",
               color_continuous_scale="viridis")
    fig.update_layout(xaxis_title="Projet", yaxis_title="Budget / jour (€)", template="plotly_white")
    return fig.to_html(full_html=False)

# ------------------ RUN ------------------
if __name__=="__main__":
    app.run(debug=True)

@app.route("/chart/timeline/<name>")
@login_required
def chart_timeline(name):
    project = next((p for p in load_json(PROJECT_FILE) if p["name"] == name), None)
    if not project:
        return "<h3>Projet introuvable</h3>"

    if not project["expenses"]:
        return "<h3 style='text-align:center'>Pas de données</h3>"

    df = pd.DataFrame(project["expenses"])

    # Convertir dates
    df["date"] = pd.to_datetime(df["date"])

    # Grouper par date
    df_grouped = df.groupby("date")["amount"].sum().reset_index()

    fig = px.line(
        df_grouped,
        x="date",
        y="amount",
        title="Évolution des dépenses dans le temps",
        markers=True
    )

    return fig.to_html(full_html=False)

@app.route("/edit_project/<name>", methods=["POST"])
@login_required
def edit_project(name):
    data = load_json(PROJECT_FILE)
    project = next((p for p in data if p["name"] == name), None)

    if not project:
        return f"Projet '{name}' introuvable"

    new_name = request.form["new_name"].strip()
    budget = float(request.form["budget"])
    start_date = request.form.get("start_date", "")
    end_date = request.form.get("end_date", "")

    # éviter doublon de nom
    if new_name != name and any(p["name"] == new_name for p in data):
        return f"Le projet '{new_name}' existe déjà"

    project["name"] = new_name
    project["budget"] = budget
    project["start_date"] = start_date
    project["end_date"] = end_date

    save_json(PROJECT_FILE, data)

    return redirect(url_for("view_project", name=new_name, success=1))
