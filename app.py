# ** importuri **

#principalele importuri 
import webview #impacheteaza aplicatia web intr o fereastra de dekstop, elimina nevoia de a folosi un browser web
from flask import Flask, render_template, request, redirect, url_for, flash, Response
from flask_sqlalchemy import SQLAlchemy  #(ORM- foloseste clase Python in loc de interogari SQL brute)
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from dotenv import load_dotenv

#securitatea datelor 
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

#cronometrul in javascript 
from datetime import datetime, timedelta

# importuri pentru AI
from google import genai
from transformers import pipeline
from PIL import Image

import os #path ul fisierelor
import io  # Adăugat pentru generarea raportului CSV
import csv # Adăugat pentru generarea raportului CSV

#configurare aplicatie 
load_dotenv()
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///mindfulcart.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

#managerul de autentificare 
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Trebuie sa fii autentificat pentru a accesa seiful!'
login_manager.login_message_category = 'warning'

# definim folosind o clasa Python 
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    venit_lunar = db.Column(db.Float, nullable=False, default=0.0)
    dorinte = db.relationship('WishItem', backref='user', lazy=True)


#definim clasa cu dorinte 
class WishItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nume = db.Column(db.String(150), nullable=False)
    pret = db.Column(db.Float, nullable=False)
    nume_poza = db.Column(db.String(150), nullable=False)
    raspuns_ai = db.Column(db.Text, nullable=False)
    procent_venit = db.Column(db.Float)
    link_produs = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(50), default='În așteptare')
    data_adaugare = db.Column(db.DateTime, default=datetime.now) 
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


@login_manager.user_loader

#returnare current_user
def load_user(user_id):
    return db.session.get(User, int(user_id))

with app.app_context():
    db.create_all()

UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

try:
    client_ai = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
except Exception as e:
    print('Eroare la conectarea cu ai, verifica cheia')
    client_ai = None

image_classifier = pipeline('image-classification', model="google/vit-base-patch16-224")


@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        venit_lunar = request.form.get('venit_lunar')
        
        user = User.query.filter_by(username=username).first()
            
        hashed_password = generate_password_hash(password, method="pbkdf2:sha256")
        new_user = User(username=username, password=hashed_password, venit_lunar=float(venit_lunar))
        db.session.add(new_user)
        db.session.commit()

        flash('Cont creat cu succes! Te poti loga.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('home'))
        else:
            flash('Date de conectare incorecte.', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def home():
    # 1. Produsele care apar în seif
    produse_in_asteptare = WishItem.query.filter_by(
        user_id=current_user.id, 
        status='În așteptare'
    ).order_by(WishItem.id.desc()).all()
    
    # 2. Calcul Statistici Utilitare
    produse_salvate = WishItem.query.filter_by(user_id=current_user.id, status='Salvat').all()
    produse_cumparate = WishItem.query.filter_by(user_id=current_user.id, status='Achiziționat').all()
    
    bani_salvati = sum(p.pret for p in produse_salvate)
    bani_cheltuiti = sum(p.pret for p in produse_cumparate)
    
    return render_template('index.html', 
                           produse=produse_in_asteptare, 
                           bani_salvati=bani_salvati, 
                           bani_cheltuiti=bani_cheltuiti)


@app.route('/analizeaza', methods=['POST'])
@login_required
def analizeaza_dorinta():
    pret_produs = float(request.form.get('pret_produs'))
    motiv = request.form.get('motiv')
    link_produs = request.form.get('link_produs')

    poza = request.files.get('poza_produs')
    nume_poza_salvata = None
    eticheta_imagine = 'Obiect nedetectat'

    if poza and poza.filename != '':
        filename = secure_filename(poza.filename)
        cale_salavata = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        poza.save(cale_salavata)
        nume_poza_salvata = filename

        try:
            img_to_analyze = Image.open(cale_salavata)
            rezultate = image_classifier(img_to_analyze)
            eticheta_imagine = rezultate[0]['label']
        except Exception as e:
            print(f"Eroare recunoaștere imagine: {e}")
            
    nume_produs = eticheta_imagine
    venit = current_user.venit_lunar
    procent = round((pret_produs/venit)*100, 2) if venit > 0 else 0
    
    prompt = f"""
        Ești un coach financiar care incearca sa combata pe cat posibil fast fashion-ul.
        Utilizatorul are un venit lunar de {venit} RON.
        Sistemul meu de recunoaștere vizuală a detectat din poză că vrea să cumpere: "{nume_produs}".
        Prețul este {pret_produs} RON, adică {procent}% din venitul lui!
        Motivul dat de el este: "{motiv}".
        Ofera-i un motiv intelept, scurt, intr-un stil prietenos, prin care sa-i sugerezi sa se regandeasca la alegerea pe care vrea s-o faca, raportandu-te la bugetul lui si motivul dat
        """
        
    try:
        if client_ai:
            response = client_ai.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            mesaj_ai = response.text.strip()
        else:
            mesaj_ai = f"Eroare de conectare la AI assistant, dar {procent}% este destul de mult!"
    except Exception as e:
        mesaj_ai = "Eroare AI Text"
        print(f"Eroare AI Text : {e}")
    
    noua_dorinta = WishItem(
        nume=nume_produs,
        pret=pret_produs,
        nume_poza=nume_poza_salvata,
        raspuns_ai=mesaj_ai,
        procent_venit=procent,
        user_id=current_user.id,
        link_produs=link_produs
    )
    
    db.session.add(noua_dorinta)
    db.session.commit()

    return redirect(url_for('home'))


#raport csv 
@app.route('/raport')
@login_required
def descarca_raport():
    produse = WishItem.query.filter_by(user_id=current_user.id).order_by(WishItem.id.desc()).all()
    
    # expanuser('~')-calea catre folderul acasa
    cale_downloads = os.path.join(os.path.expanduser('~'), 'Downloads', 'raport_financiar_mindfulcart.csv')
    
    # 2. Creăm și salvăm raportul acolo
    with open(cale_downloads, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['Data Adaugare', 'Nume Produs', 'Pret (RON)', 'Procent Venit (%)', 'Status Decizie'])
        
        for p in produse:
            data_fmt = p.data_adaugare.strftime('%Y-%m-%d %H:%M') if p.data_adaugare else 'N/A'
            writer.writerow([
                data_fmt, 
                p.nume, 
                p.pret, 
                p.procent_venit, 
                p.status
            ])
            
    return redirect(url_for('home'))

@app.route('/decide/<int:produs_id>/<string:actiune>')
@login_required
def decide_produs(produs_id, actiune):
    produs = db.session.get(WishItem, produs_id)

    if produs and produs.user_id == current_user.id:
        if actiune == 'cumparat':
            produs.status = 'Achiziționat' # Corectat din 'Cumparat' pentru a funcționa statisticile
            flash(f"Ai achizitionat {produs.nume}.", 'info')
        elif actiune == 'salvat':
            produs.status = 'Salvat'
            flash(f"Felicitari! Ai salvat banii pentru {produs.nume}.", 'success') # Corectat ghilimelele eronate

        db.session.commit()
    return redirect(url_for('home'))


if __name__ == '__main__':
    # Creăm fereastra desktop webview
    webview.create_window('MindfulCart - Seiful Dorințelor', app, width=1200, height=850)
    webview.start()