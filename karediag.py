#!/usr/bin/env python3
import sys
import re
import subprocess
import json
import os
import shlex
import shutil
import glob
import getpass
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton, QComboBox, QMessageBox,
    QTextEdit, QDialog, QFileDialog, QStackedWidget, QSizePolicy,
    QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QScrollArea, QFrame
)
from PyQt5.QtCore import Qt, QTimer, QProcess
from PyQt5.QtGui import QColor, QBrush

NOM_APPLICATION = "KareDiag"


# ============================================================
# KareDiag - Gestion des privilèges
# Authentification unique : l'application est élevée en root
# une seule fois au lancement (via PolicyKit), comme GParted.
# ============================================================
def est_root():
    return os.geteuid() == 0


def prefixe_privilege():
    """Préfixe des commandes sensibles : vide si KareDiag tourne déjà en root."""
    return [] if est_root() else ["pkexec"]


def elever_application():
    """Une seule demande PolicyKit au lancement : relance KareDiag en root.

    Renvoie le code retour de l'instance élevée (0 si fermée normalement).
    """
    script = os.path.abspath(__file__)
    env_args = [
        f"{var}={os.environ[var]}" for var in (
            "DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR",
            "XDG_SESSION_TYPE", "DBUS_SESSION_BUS_ADDRESS", "HOME", "LANG",
        ) if var in os.environ
    ]
    try:
        return subprocess.run(
            ["pkexec", "env"] + env_args + [sys.executable, script]
        ).returncode
    except Exception:
        return 1


def bureau_utilisateur():
    """Chemin du bureau de l'utilisateur (Desktop ou Bureau), sinon HOME."""
    return os.path.expanduser(
        next((p for p in ["~/Desktop", "~/Bureau"]
              if os.path.isdir(os.path.expanduser(p))), "~")
    )


class RapportWindow(QDialog):
    """Fenêtre dédiée pour afficher les rapports SMART au format texte"""
    def __init__(self, titre, contenu_texte):
        super().__init__(parent=None)
        self.setWindowTitle(titre)
        self.resize(750, 600)

        layout = QVBoxLayout(self)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setPlainText(contenu_texte)
        self.text_edit.setStyleSheet("""
            background-color: #121417;
            color: #98c379;
            font-family: monospace;
            font-size: 12px;
            border: 1px solid #3e4451;
            border-radius: 4px;
        """)

        layout.addWidget(self.text_edit)

        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("Enregistrer en .txt")
        self.btn_save.clicked.connect(self.sauvegarder_fichier)
        self.btn_close = QPushButton("Fermer")
        self.btn_close.clicked.connect(self.close)

        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)

        self.contenu = contenu_texte

    def sauvegarder_fichier(self):
        try:
            chemin = os.path.join(
                bureau_utilisateur(), "rapport_karediag_smart.txt"
            )
            with open(chemin, "w", encoding="utf-8") as f:
                f.write(self.contenu)
            QMessageBox.information(self, "Succès", f"Rapport enregistré sur le bureau :\n{chemin}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Impossible d'enregistrer :\n{e}")


class KPVWindow(QDialog):
    """KareDiag - Périphériques : tests USB, réseau et périphériques d'entrée.
    Tous les tests sont lisibles sans privilèges : aucun root requis."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KareDiag - Tests des périphériques (Zone 8)")
        self.resize(720, 620)
        self.setMinimumSize(650, 550)

        self.setStyleSheet("""
            QDialog { background-color: #181a1f; }
            QGroupBox {
                color: #00bcd4;
                font-weight: bold;
                font-size: 13px;
                border: 2px solid #3e4451;
                border-radius: 8px;
                margin-top: 12px;
                background-color: rgba(33, 37, 43, 210);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 5px;
            }
            QPushButton {
                background-color: #2188ff;
                color: white;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover { background-color: #006fe6; }
            QPushButton:disabled { background-color: #3b4252; color: #606b7d; }
            QLabel { color: #abb2bf; font-size: 12px; }
        """)

        layout = QVBoxLayout(self)

        titre = QLabel("KareDiag - Tests de validation matérielle")
        titre.setStyleSheet("font-size: 14px; font-weight: bold; color: #00bcd4;")
        titre.setAlignment(Qt.AlignCenter)
        layout.addWidget(titre)

        # Voyants d'état
        indicators_frame = QGroupBox(" État des modules de test ")
        grid = QGridLayout(indicators_frame)

        self.voyant_usb = self.creer_voyant()
        self.voyant_net = self.creer_voyant()
        self.voyant_input = self.creer_voyant()

        grid.addWidget(self.voyant_usb, 0, 0)
        grid.addWidget(QLabel("Périphériques USB (bus & périphériques)"), 0, 1)
        grid.addWidget(self.voyant_net, 1, 0)
        grid.addWidget(QLabel("Interfaces réseau & connectivité Internet"), 1, 1)
        grid.addWidget(self.voyant_input, 2, 0)
        grid.addWidget(QLabel("Périphériques d'entrée (claviers, souris, événements)"), 2, 1)
        layout.addWidget(indicators_frame)

        # Boutons
        btn_frame = QHBoxLayout()
        self.run_btn = QPushButton("▶ Lancer les tests")
        self.run_btn.clicked.connect(self.run_all_tests)
        self.save_btn = QPushButton("💾 Exporter le rapport (JSON)")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save_report)

        btn_frame.addWidget(self.run_btn)
        btn_frame.addWidget(self.save_btn)
        layout.addLayout(btn_frame)

        # Journal
        log_frame = QGroupBox(" Journal des opérations et détails ")
        log_layout = QVBoxLayout(log_frame)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            background-color: #1e1e1e;
            color: #00ff00;
            font-family: monospace;
            font-size: 10px;
            border: 1px solid #3e4451;
            border-radius: 4px;
        """)
        log_layout.addWidget(self.log_text)
        layout.addWidget(log_frame)

        self.last_report = None

    def creer_voyant(self):
        voyant = QLabel()
        voyant.setFixedSize(18, 18)
        voyant.setStyleSheet("background-color: #606b7d; border-radius: 9px;")
        return voyant

    def set_voyant(self, voyant, couleur):
        voyant.setStyleSheet(f"background-color: {couleur}; border-radius: 9px;")

    def log(self, message):
        self.log_text.append(message)

    def run_cmd(self, command, timeout=15):
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
            return {"success": result.returncode == 0,
                    "output": result.stdout.strip() or result.stderr.strip()}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def run_all_tests(self):
        self.log_text.clear()
        self.log(f"=== Début des tests KareDiag - {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} ===")

        self.set_voyant(self.voyant_usb, "#606b7d")
        self.set_voyant(self.voyant_net, "#606b7d")
        self.set_voyant(self.voyant_input, "#606b7d")
        self.save_btn.setEnabled(False)
        QApplication.processEvents()

        self.last_report = {
            "timestamp": datetime.now().isoformat(),
            "execution_user": getpass.getuser(),
        }

        # Test USB
        self.log("\n[*] Analyse du bus USB...")
        res_usb = self.run_cmd(["lsusb"])
        if res_usb["success"] and res_usb["output"]:
            count = len(res_usb["output"].splitlines())
            self.log(f"[OK] Succès : {count} périphériques détectés.")
            self.set_voyant(self.voyant_usb, "#4CAF50")
            self.last_report["usb"] = {"status": "PASS", "details": res_usb["output"]}
        else:
            self.log(f"[KO] Échec USB : {res_usb['output']}")
            self.set_voyant(self.voyant_usb, "#F44336")
            self.last_report["usb"] = {"status": "FAIL", "details": res_usb["output"]}
        QApplication.processEvents()

        # Test Réseau
        self.log("\n[*] Analyse des interfaces réseau...")
        res_net = self.run_cmd(["ip", "-br", "link", "show"])
        ping_res = self.run_cmd(["ping", "-c", "1", "-W", "3", "8.8.8.8"], timeout=10)
        connectivity = "ONLINE" if ping_res["success"] else "OFFLINE"
        if res_net["success"]:
            self.log(f"[OK] Interfaces réseau lues. Connectivité Internet : {connectivity}")
            self.set_voyant(self.voyant_net, "#4CAF50")
            self.last_report["network"] = {
                "status": "PASS",
                "interfaces": res_net["output"],
                "connectivity": connectivity,
            }
        else:
            self.log("[KO] Échec de la lecture des interfaces réseau.")
            self.set_voyant(self.voyant_net, "#F44336")
            self.last_report["network"] = {"status": "FAIL", "details": res_net["output"]}
        QApplication.processEvents()

        # Test Entrées
        self.log("\n[*] Analyse des périphériques d'entrée...")
        try:
            with open("/proc/bus/input/devices", "r", encoding="utf-8") as f:
                lignes = [l.rstrip() for l in f if l.startswith("N:") or l.startswith("H:")]
            if lignes:
                nb = sum(1 for l in lignes if l.startswith("N:"))
                self.log(f"[OK] Succès : {nb} périphériques d'entrée reconnus par le noyau.")
                self.set_voyant(self.voyant_input, "#4CAF50")
                self.last_report["input_devices"] = {"status": "PASS", "details": "\n".join(lignes)}
            else:
                raise ValueError("Aucun périphérique d'entrée listé")
        except Exception as e:
            self.log(f"[KO] Échec de la lecture des périphériques d'entrée : {e}")
            self.set_voyant(self.voyant_input, "#F44336")
            self.last_report["input_devices"] = {"status": "FAIL", "details": str(e)}

        self.log("\n=== Fin de l'exécution des tests ===")
        self.save_btn.setEnabled(True)

    def save_report(self):
        if not self.last_report:
            return
        home_dir = os.path.expanduser("~")
        report_path = os.path.join(
            home_dir, f"karediag_peripheriques_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(self.last_report, f, indent=4, ensure_ascii=False)
            QMessageBox.information(self, "Rapport exporté",
                                    f"Le rapport JSON a été enregistré ici :\n{report_path}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Erreur lors de l'enregistrement :\n{e}")


# ============================================================
# KareDiag - Zone 11 : vérification des mises à jour et paquets
# (Debian/Kaisen : APT/DPKG — contrôles sans modification)
# ============================================================
class KMAJWindow(QDialog):
    """Zone 11 : état des mises à jour et santé des paquets APT/DPKG."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KareDiag - Vérification des mises à jour et paquets (Zone 11)")
        self.resize(780, 620)
        self.setMinimumSize(700, 560)

        self.setStyleSheet("""
            QDialog { background-color: #181a1f; }
            QGroupBox {
                color: #00bcd4;
                font-weight: bold;
                font-size: 13px;
                border: 2px solid #3e4451;
                border-radius: 8px;
                margin-top: 12px;
                background-color: rgba(33, 37, 43, 210);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 5px;
            }
            QPushButton {
                background-color: #2188ff;
                color: white;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover { background-color: #006fe6; }
            QPushButton:disabled { background-color: #3b4252; color: #606b7d; }
            QLabel { color: #abb2bf; font-size: 12px; }
        """)

        layout = QVBoxLayout(self)

        titre = QLabel("KareDiag - Vérification des mises à jour et paquets")
        titre.setStyleSheet("font-size: 14px; font-weight: bold; color: #00bcd4;")
        titre.setAlignment(Qt.AlignCenter)
        layout.addWidget(titre)

        note = QLabel(
            "Contrôles APT/DPKG (aucune modification du système).\n"
            "« Actualiser les listes » requiert l'authentification PolicyKit ;\n"
            "les autres vérifications se font sans privilèges."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        btn_frame = QGridLayout()
        self.btn_update = QPushButton("Actualiser les listes (apt update)")
        self.btn_update.clicked.connect(self.lancer_maj_listes)
        self.btn_upgradable = QPushButton("Paquets à mettre à jour")
        self.btn_upgradable.clicked.connect(self.lister_maj_disponibles)
        self.btn_brises = QPushButton("Paquets brisés / dépendances")
        self.btn_brises.clicked.connect(self.verifier_paquets_bries)
        self.btn_orphelins = QPushButton("Paquets orphelins (autoremove)")
        self.btn_orphelins.clicked.connect(self.lister_orphelins)
        self.btn_export = QPushButton("Exporter le rapport")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.exporter_rapport)

        btn_frame.addWidget(self.btn_update, 0, 0)
        btn_frame.addWidget(self.btn_upgradable, 0, 1)
        btn_frame.addWidget(self.btn_brises, 1, 0)
        btn_frame.addWidget(self.btn_orphelins, 1, 1)
        btn_frame.addWidget(self.btn_export, 2, 0, 1, 2)
        layout.addLayout(btn_frame)

        log_frame = QGroupBox(" Rapport des vérifications ")
        log_layout = QVBoxLayout(log_frame)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            background-color: #1e1e1e;
            color: #00ff00;
            font-family: monospace;
            font-size: 10px;
            border: 1px solid #3e4451;
            border-radius: 4px;
        """)
        log_layout.addWidget(self.log_text)
        layout.addWidget(log_frame)

        self.boutons = [self.btn_update, self.btn_upgradable, self.btn_brises, self.btn_orphelins]

    def log(self, message):
        self.log_text.append(message)
        QApplication.processEvents()

    def set_boutons(self, actif):
        for bouton in self.boutons:
            bouton.setEnabled(actif)

    def run_cmd(self, commande, timeout=300):
        try:
            res = subprocess.run(commande, capture_output=True, text=True, timeout=timeout)
            return res.returncode == 0, ((res.stdout or "") + (res.stderr or ""))
        except FileNotFoundError:
            return False, f"Commande introuvable : {commande[0]}"
        except Exception as e:
            return False, str(e)

    def afficher_sortie(self, sortie, max_lignes=60):
        lignes = [l for l in sortie.splitlines() if l.strip()]
        if len(lignes) > max_lignes:
            lignes = lignes[:max_lignes] + [
                f"... ({len(lignes) - max_lignes} lignes supplémentaires omises)"]
        for l in lignes:
            self.log("   " + l)

    def lancer_maj_listes(self):
        if shutil.which("apt-get") is None:
            self.log("[KO] apt-get introuvable : vérification réservée aux "
                     "distributions à base de Debian (Kaisen Linux).")
            return
        self.set_boutons(False)
        self.log(f"\n[{datetime.now().strftime('%H:%M:%S')}] "
                 "Actualisation des listes de paquets (apt-get update)...")
        ok, sortie = self.run_cmd(prefixe_privilege() + ["apt-get", "update"], timeout=600)
        self.afficher_sortie(sortie)
        if ok:
            self.log("[OK] Listes de paquets actualisées.")
        else:
            self.log("[KO] Échec de l'actualisation (authentification refusée "
                     "ou dépôts inaccessibles).")
        self.set_boutons(True)

    def lister_maj_disponibles(self):
        if shutil.which("apt") is None:
            self.log("[KO] apt introuvable : vérification réservée aux "
                     "distributions à base de Debian (Kaisen Linux).")
            return
        self.set_boutons(False)
        self.log("\n[*] Recherche des paquets à mettre à jour...")
        ok, sortie = self.run_cmd(["env", "LC_ALL=C", "apt", "list", "--upgradable"])
        paquets = [l for l in sortie.splitlines() if "/" in l]
        if ok and paquets:
            self.log(f"[ALERTE] {len(paquets)} paquet(s) peuvent être mis à jour :")
            self.afficher_sortie("\n".join(paquets))
            self.log("[i] Utilisez « sudo apt upgrade » pour les installer.")
        elif ok:
            self.log("[OK] Aucune mise à jour disponible : le système est à jour.")
        else:
            self.log(f"[KO] Échec de la lecture des mises à jour : {sortie.strip()}")
        self.set_boutons(True)

    def verifier_paquets_bries(self):
        self.set_boutons(False)
        self.log("\n[*] Vérification de l'état des paquets (dpkg --audit)...")
        ok, sortie = self.run_cmd(["env", "LC_ALL=C", "dpkg", "--audit"])
        if sortie.strip():
            self.log("[ALERTE] Des paquets sont endommagés ou incohérents :")
            self.afficher_sortie(sortie)
            self.log("[i] Lancez « sudo dpkg --configure -a » puis "
                     "« sudo apt install -f » pour réparer.")
        else:
            self.log("[OK] DPKG : aucun paquet endommagé.")
        if shutil.which("apt-get") is None:
            self.set_boutons(True)
            return
        self.log("[*] Simulation de correction des dépendances (apt-get -s install -f)...")
        ok2, sortie2 = self.run_cmd(["env", "LC_ALL=C", "apt-get", "-s", "install", "-f"])
        actions = [l for l in sortie2.splitlines() if l.startswith(("Inst ", "Remv ", "Purg "))]
        if ok2:
            if actions:
                self.log(f"[ALERTE] Des dépendances demandent une correction "
                         f"({len(actions)} action(s) simulée(s)) :")
                self.afficher_sortie("\n".join(actions))
            else:
                self.log("[OK] Dépendances APT : aucune correction nécessaire.")
        else:
            self.log(f"[KO] Simulation impossible : {sortie2.strip()}")
        self.set_boutons(True)

    def lister_orphelins(self):
        if shutil.which("apt-get") is None:
            self.log("[KO] apt-get introuvable : vérification réservée aux "
                     "distributions à base de Debian (Kaisen Linux).")
            return
        self.set_boutons(False)
        self.log("\n[*] Recherche des paquets orphelins (simulation d'autoremove)...")
        ok, sortie = self.run_cmd(["env", "LC_ALL=C", "apt-get", "-s", "autoremove"])
        orphelins = [l for l in sortie.splitlines() if l.startswith(("Remv ", "Purg "))]
        if ok and orphelins:
            self.log(f"[i] {len(orphelins)} paquet(s) devenu(s) orphelin(s) :")
            self.afficher_sortie("\n".join(orphelins))
            self.log("[i] « sudo apt autoremove » les supprimera (vérifiez la liste avant).")
        elif ok:
            self.log("[OK] Aucun paquet orphelin.")
        else:
            self.log(f"[KO] Simulation impossible : {sortie.strip()}")
        self.set_boutons(True)

    def exporter_rapport(self):
        RapportWindow("Rapport - Mises à jour et paquets (Zone 11)",
                      self.log_text.toPlainText()).exec_()


# ============================================================
# KareDiag - Zone 12 : journal d'exécution direct (journalctl)
# Affichage en temps réel avec filtres, priorités et export.
# ============================================================
class KJournalWindow(QDialog):
    """Zone 12 : suivi en direct du journal système via journalctl."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KareDiag - Journal d'exécution direct (Zone 12)")
        self.resize(860, 640)
        self.setMinimumSize(760, 560)

        self.setStyleSheet("""
            QDialog { background-color: #181a1f; }
            QGroupBox {
                color: #00bcd4;
                font-weight: bold;
                font-size: 13px;
                border: 2px solid #3e4451;
                border-radius: 8px;
                margin-top: 12px;
                background-color: rgba(33, 37, 43, 210);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 5px;
            }
            QPushButton {
                background-color: #2188ff;
                color: white;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover { background-color: #006fe6; }
            QPushButton:disabled { background-color: #3b4252; color: #606b7d; }
            QLabel, QComboBox { color: #abb2bf; font-size: 12px; }
            QComboBox, QLineEdit {
                background-color: #21252b;
                border: 1px solid #4b5263;
                border-radius: 4px;
                padding: 4px;
                color: #abb2bf;
            }
        """)

        layout = QVBoxLayout(self)

        titre = QLabel("KareDiag - Journal d'exécution direct")
        titre.setStyleSheet("font-size: 14px; font-weight: bold; color: #00bcd4;")
        titre.setAlignment(Qt.AlignCenter)
        layout.addWidget(titre)

        note = QLabel(
            "Journal système en direct (journalctl). Sans privilèges, une partie du "
            "journal système peut rester masquée : ajoutez votre utilisateur aux groupes "
            "« systemd-journal » et « adm », ou utilisez le mode administrateur."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        ctrl_frame = QGroupBox(" Contrôles du suivi ")
        grid = QGridLayout(ctrl_frame)

        grid.addWidget(QLabel("Source :"), 0, 0)
        self.combo_source = QComboBox()
        self.combo_source.addItems(["Système complet", "Noyau (dmesg)", "Session utilisateur"])
        grid.addWidget(self.combo_source, 0, 1)

        grid.addWidget(QLabel("Priorité minimale :"), 0, 2)
        self.combo_prio = QComboBox()
        self.combo_prio.addItems(
            ["Toutes", "Information et supérieur", "Avertissements et supérieur", "Erreurs et supérieur"])
        grid.addWidget(self.combo_prio, 0, 3)

        grid.addWidget(QLabel("Filtre texte :"), 1, 0)
        self.ed_filtre = QLineEdit()
        self.ed_filtre.setPlaceholderText("N'affiche que les lignes contenant ce texte...")
        grid.addWidget(self.ed_filtre, 1, 1, 1, 3)
        layout.addWidget(ctrl_frame)

        btn_frame = QHBoxLayout()
        self.btn_suivi = QPushButton("▶ Démarrer le suivi")
        self.btn_suivi.clicked.connect(self.basculer_suivi)
        self.btn_pause = QPushButton("⏸ Pause")
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self.basculer_pause)
        self.btn_export = QPushButton("Sauvegarder le journal")
        self.btn_export.clicked.connect(self.sauvegarder)
        self.btn_vider = QPushButton("Vider l'affichage")

        btn_frame.addWidget(self.btn_suivi)
        btn_frame.addWidget(self.btn_pause)
        btn_frame.addWidget(self.btn_export)
        btn_frame.addWidget(self.btn_vider)
        layout.addLayout(btn_frame)

        log_frame = QGroupBox(" Journal en direct ")
        log_layout = QVBoxLayout(log_frame)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            background-color: #1e1e1e;
            color: #00ff00;
            font-family: monospace;
            font-size: 10px;
            border: 1px solid #3e4451;
            border-radius: 4px;
        """)
        log_layout.addWidget(self.log_text)
        layout.addWidget(log_frame)

        self.process = None
        self.tampon = ""
        self.en_pause = False
        self.file_pause = []
        self.couleur_normale = QColor("#00ff00")
        self.btn_vider.clicked.connect(self.log_text.clear)

    def log(self, message, couleur=None):
        if couleur is not None:
            self.log_text.setTextColor(couleur)
        self.log_text.append(message)
        self.log_text.setTextColor(self.couleur_normale)

    def args_journal(self):
        args = ["journalctl", "-f", "-n", "200", "--no-pager"]
        source = self.combo_source.currentIndex()
        if source == 1:
            args.append("-k")
        elif source == 2:
            args.append("--user")
        prio = ["", "6", "4", "3"][self.combo_prio.currentIndex()]
        if prio:
            args += ["-p", prio]
        return args

    def basculer_suivi(self):
        if self.process is None:
            self.demarrer_suivi()
        else:
            self.arreter_suivi()

    def demarrer_suivi(self):
        if shutil.which("journalctl") is None:
            self.log("[KO] journalctl introuvable sur ce système.", QColor("#e06c75"))
            return
        args = self.args_journal()
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.lire_sortie)
        self.process.finished.connect(self.suivi_termine)
        self.process.errorOccurred.connect(self.erreur_processus)
        self.process.start(args[0], args[1:])
        self.tampon = ""
        self.file_pause = []
        self.en_pause = False
        self.btn_pause.setText("⏸ Pause")
        self.btn_pause.setEnabled(True)
        self.btn_suivi.setText("■ Arrêter le suivi")
        self.log(f"[i] Suivi démarré ({args[2:]}) : les nouvelles entrées s'affichent ici.",
                 QColor("#e5c07b"))

    def arreter_suivi(self):
        if self.process is None:
            return
        self.process.kill()
        self.process.waitForFinished(2000)
        self.process = None
        self.btn_suivi.setText("▶ Démarrer le suivi")
        self.btn_pause.setEnabled(False)
        self.log("[i] Suivi arrêté.", QColor("#e5c07b"))

    def basculer_pause(self):
        self.en_pause = not self.en_pause
        self.btn_pause.setText("▶ Reprendre" if self.en_pause else "⏸ Pause")
        if not self.en_pause:
            for ligne in self.file_pause:
                self.ajouter_ligne(ligne)
            self.file_pause = []

    def lire_sortie(self):
        data = self.process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        self.tampon += data
        if "\n" not in self.tampon:
            return
        lignes, self.tampon = self.tampon.rsplit("\n", 1)
        for ligne in lignes.splitlines():
            self.ajouter_ligne(ligne)

    def ajouter_ligne(self, ligne):
        filtre = self.ed_filtre.text().strip().lower()
        if filtre and filtre not in ligne.lower():
            return
        if self.en_pause:
            self.file_pause.append(ligne)
            if len(self.file_pause) > 2000:
                self.file_pause.pop(0)
            return
        bas = ligne.lower()
        rouge = any(m in bas for m in (
            "error", "erreur", "failed", "échec", "critique", "critical", "fatal",
            "emerg", "segfault", "segmentation fault", "out of memory", "oom-killer"))
        jaune = not rouge and any(m in bas for m in (
            "warn", "avertissement", "attention", "timeout", "refused", "degraded"))
        if rouge:
            self.log(ligne, QColor("#e06c75"))
        elif jaune:
            self.log(ligne, QColor("#e5c07b"))
        else:
            self.log(ligne)

    def suivi_termine(self):
        if self.process is not None:
            self.process = None
            self.btn_suivi.setText("▶ Démarrer le suivi")
            self.btn_pause.setEnabled(False)
            self.log("[i] Suivi terminé (commande terminée).", QColor("#e5c07b"))

    def erreur_processus(self, erreur):
        self.log(f"[KO] journalctl : {erreur}", QColor("#e06c75"))
        self.process = None
        self.btn_suivi.setText("▶ Démarrer le suivi")
        self.btn_pause.setEnabled(False)

    def sauvegarder(self):
        chemin, _ = QFileDialog.getSaveFileName(
            self, "Sauvegarder le journal",
            os.path.join(bureau_utilisateur(),
                         f"karediag_journal_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"),
            "Fichiers texte (*.txt)")
        if not chemin:
            return
        try:
            with open(chemin, "w", encoding="utf-8") as f:
                f.write(self.log_text.toPlainText())
            QMessageBox.information(self, "Journal exporté",
                                    f"Le journal a été enregistré ici :\n{chemin}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur",
                                 f"Erreur lors de l'enregistrement :\n{e}")

    def closeEvent(self, event):
        self.arreter_suivi()
        event.accept()


# ============================================================
# KareDiag - Zone 13 : détection des signes d'alerte système
# (unités en échec, erreurs noyau, OOM, surchauffe, disques saturés)
# ============================================================
class KAlertesWindow(QDialog):
    """Zone 13 : scan des signes d'alerte du système avec sévérité."""
    MOTIFS = [
        ("Mémoire : kill OOM (manque de RAM) détecté", [r"out of memory", r"oom-?killer", r"killed process"], True),
        ("Disques : erreurs d'E/S ou de système de fichiers",
         [r"i/o error", r"ext4-fs error", r"read-only file system", r"bad block",
          r"medium error", r"scsi error"], True),
        ("Matériel : erreurs ATA/NVMe", [r"ata\d+.*\berror\b", r"nvme\d+.*\berror\b", r"nvme\d+.*timeout"], False),
        ("Processus : segfault détecté", [r"segmentation fault", r"general protection fault"], False),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KareDiag - Détection des signes d'alerte système (Zone 13)")
        self.resize(860, 640)
        self.setMinimumSize(760, 560)

        self.setStyleSheet("""
            QDialog { background-color: #181a1f; }
            QGroupBox {
                color: #00bcd4;
                font-weight: bold;
                font-size: 13px;
                border: 2px solid #3e4451;
                border-radius: 8px;
                margin-top: 12px;
                background-color: rgba(33, 37, 43, 210);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 5px;
            }
            QPushButton {
                background-color: #2188ff;
                color: white;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover { background-color: #006fe6; }
            QPushButton:disabled { background-color: #3b4252; color: #606b7d; }
            QLabel { color: #abb2bf; font-size: 12px; }
        """)

        layout = QVBoxLayout(self)

        titre = QLabel("KareDiag - Détection des signes d'alerte système")
        titre.setStyleSheet("font-size: 14px; font-weight: bold; color: #00bcd4;")
        titre.setAlignment(Qt.AlignCenter)
        layout.addWidget(titre)

        note = QLabel(
            "Analyse du journal et du matériel : unités systemd en échec, erreurs de "
            "disques, manque de mémoire, surchauffe, partitions saturées. "
            "Sans privilèges, le journal système complet peut rester partiellement inaccessible."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        btn_frame = QHBoxLayout()
        self.btn_scan = QPushButton("🔍 Scanner maintenant")
        self.btn_scan.clicked.connect(self.scanner)
        self.btn_export = QPushButton("Exporter le rapport")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.exporter_rapport)

        btn_frame.addWidget(self.btn_scan)
        btn_frame.addWidget(self.btn_export)
        layout.addLayout(btn_frame)

        self.lbl_resume = QLabel("Aucun scan effectué.")
        self.lbl_resume.setStyleSheet("font-weight: bold; color: #e5c07b;")
        layout.addWidget(self.lbl_resume)

        log_frame = QGroupBox(" Résultat du scan ")
        log_layout = QVBoxLayout(log_frame)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            background-color: #1e1e1e;
            color: #00ff00;
            font-family: monospace;
            font-size: 10px;
            border: 1px solid #3e4451;
            border-radius: 4px;
        """)
        log_layout.addWidget(self.log_text)
        layout.addWidget(log_frame)

        self.nb_critiques = 0
        self.nb_avertissements = 0

    def log(self, message):
        self.log_text.append(message)
        QApplication.processEvents()

    def signaler(self, critique, message):
        if critique:
            self.nb_critiques += 1
            self.log(f"[CRITIQUE] {message}")
        else:
            self.nb_avertissements += 1
            self.log(f"[AVERTISSEMENT] {message}")

    def run_cmd(self, commande, timeout=120):
        try:
            res = subprocess.run(commande, capture_output=True, text=True, timeout=timeout)
            return res.returncode == 0, ((res.stdout or "") + (res.stderr or ""))
        except FileNotFoundError:
            return False, f"Commande introuvable : {commande[0]}"
        except Exception as e:
            return False, str(e)

    def scanner(self):
        self.btn_scan.setEnabled(False)
        self.log_text.clear()
        self.nb_critiques = 0
        self.nb_avertissements = 0
        self.log(f"=== Scan des signes d'alerte du "
                 f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')} ===\n")

        self.verifier_unites_echec()
        self.verifier_journal_erreurs()
        self.verifier_journal_noyau()
        self.verifier_capteurs()
        self.verifier_partitions_saturees()
        self.verifier_memoire()

        resume = (f"Scan terminé : {self.nb_critiques} critique(s), "
                  f"{self.nb_avertissements} avertissement(s).")
        self.log("")
        self.log("=== " + resume + " ===")
        if self.nb_critiques == 0 and self.nb_avertissements == 0:
            self.lbl_resume.setText("✅ " + resume)
            self.lbl_resume.setStyleSheet("font-weight: bold; color: #98c379;")
        elif self.nb_critiques == 0:
            self.lbl_resume.setText("⚠️ " + resume)
            self.lbl_resume.setStyleSheet("font-weight: bold; color: #e5c07b;")
        else:
            self.lbl_resume.setText("🛑 " + resume)
            self.lbl_resume.setStyleSheet("font-weight: bold; color: #e06c75;")
        self.btn_export.setEnabled(True)
        self.btn_scan.setEnabled(True)

    def verifier_unites_echec(self):
        self.log("[*] Unités systemd en échec...")
        ok, sortie = self.run_cmd(
            ["env", "LC_ALL=C", "systemctl", "list-units",
             "--state=failed", "--no-legend", "--no-pager"])
        if not ok:
            self.log("[INFO] systemctl indisponible ou inaccessible.")
            return
        unites = [l.strip() for l in sortie.splitlines() if " failed " in l]
        if unites:
            self.signaler(True, f"{len(unites)} unité(s) systemd en échec :")
            for l in unites[:15]:
                self.log("   " + l)
        else:
            self.log("[OK] Aucune unité systemd en échec.")

    def verifier_journal_erreurs(self):
        self.log("[*] Entrées de niveau ERREUR depuis le démarrage (journalctl -p 3)...")
        ok, sortie = self.run_cmd(
            ["env", "LC_ALL=C", "journalctl", "-p", "3", "-b", "-q", "--no-pager"],
            timeout=180)
        if not ok:
            self.log("[INFO] Journal système inaccessible sans privilèges (scan partiel).")
            return
        lignes = sortie.splitlines()
        if lignes:
            self.signaler(False, f"{len(lignes)} entrée(s) de niveau ERREUR depuis le démarrage :")
            for l in lignes[-30:]:
                self.log("   " + l)
        else:
            self.log("[OK] Aucune erreur système enregistrée depuis le démarrage.")

    def verifier_journal_noyau(self):
        self.log("[*] Journal noyau : OOM, disques, matériel...")
        ok, sortie = self.run_cmd(
            ["env", "LC_ALL=C", "journalctl", "-k", "-b", "-q", "--no-pager"],
            timeout=180)
        if not ok:
            self.log("[INFO] Journal noyau inaccessible sans privilèges.")
            return
        interroges = 0
        for libelle, motifs, critique in self.MOTIFS:
            correspondances = [l for l in sortie.splitlines()
                               if any(re.search(m, l, re.IGNORECASE) for m in motifs)]
            if correspondances:
                self.signaler(critique, f"{libelle} — {len(correspondances)} entrée(s) :")
                for l in correspondances[-10:]:
                    self.log("   " + l)
                interroges += 1
        if interroges == 0:
            self.log("[OK] Aucun motif d'alerte détecté dans le journal noyau.")

    def verifier_capteurs(self):
        self.log("[*] Capteurs : températures et alarmes matérielles...")
        capteurs = mesures_hwmon()
        alertes = 0
        for capteur in capteurs:
            if capteur["etat"] != "OK":
                alertes += 1
                texte = (f"{capteur['source']} : {capteur['nom']} = "
                         f"{capteur['valeur']} {capteur['unite']} "
                         f"(limite {capteur['limite']})")
                self.signaler(capteur["etat"] == "ALERTE", texte)
        if alertes == 0:
            self.log(f"[OK] {len(capteurs)} capteur(s) interrogé(s), aucune alerte.")

    def verifier_partitions_saturees(self):
        self.log("[*] Espace disque des partitions montées...")
        ok, sortie = self.run_cmd(["df", "-P"])
        if not ok:
            self.log("[INFO] Lecture de l'espace disque impossible.")
            return
        saturees = 0
        for ligne in sortie.splitlines()[1:]:
            champs = ligne.split()
            if len(champs) < 6 or not champs[0].startswith("/dev/"):
                continue
            if any(champs[0].startswith(p) for p in ("/dev/loop", "/dev/squashfs")):
                continue
            try:
                pourcentage = int(champs[4].rstrip("%"))
            except ValueError:
                continue
            if pourcentage > 95:
                self.signaler(True, f"{champs[0]} monté sur {champs[5]} : {pourcentage} % occupé.")
                saturees += 1
            elif pourcentage > 90:
                self.signaler(False, f"{champs[0]} monté sur {champs[5]} : {pourcentage} % occupé.")
                saturees += 1
        if saturees == 0:
            self.log("[OK] Aucune partition saturée (> 90 %).")

    def verifier_memoire(self):
        self.log("[*] Mémoire vive et swap...")
        informations = {}
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for ligne in f:
                    cle, _, reste = ligne.partition(":")
                    informations[cle.strip()] = int(reste.strip().split()[0])
        except (OSError, ValueError, IndexError):
            self.log("[INFO] Lecture de /proc/meminfo impossible.")
            return
        total = informations.get("MemTotal", 0)
        disponible = informations.get("MemAvailable", total)
        swap_total = informations.get("SwapTotal", 0)
        swap_libre = informations.get("SwapFree", 0)
        if total and disponible / total < 0.05:
            self.signaler(True, f"Mémoire vive presque saturée : {disponible // 1024} Mo disponibles sur {total // 1024} Mo.")
        else:
            self.log("[OK] Mémoire vive disponible.")
        if swap_total and swap_libre / swap_total < 0.10:
            self.signaler(False, f"Swap presque saturé : {int(100 * swap_libre / swap_total)} % libre.")

    def exporter_rapport(self):
        RapportWindow("Rapport - Signes d'alerte (Zone 13)",
                      self.log_text.toPlainText()).exec_()


# ============================================================
# KareDiag - Zone 15 : utilitaires capteurs (hwmon), vitesses
# CPU et charge — lecture directe, sans privilèges
# ============================================================
def lire_texte_fichier(chemin):
    try:
        with open(chemin, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def lire_entier_fichier(chemin, diviseur=1):
    try:
        return int(lire_texte_fichier(chemin)) / diviseur
    except (ValueError, OSError):
        return None


def capteur_etat(alarme, ratio):
    """État d'un capteur : ALERTE / À surveiller / OK (ratio : valeur / limite critique)."""
    if alarme or (ratio is not None and ratio >= 0.9):
        return "ALERTE"
    if ratio is not None and ratio >= 0.75:
        return "À surveiller"
    return "OK"


def mesures_hwmon():
    """Liste des capteurs de la carte mère depuis /sys/class/hwmon :
    températures, ventilateurs, tensions, courants et puissances."""
    capteurs = []
    for chemin_chip in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        nom_chip = lire_texte_fichier(os.path.join(chemin_chip, "name")) or "inconnu"

        for chemin in sorted(glob.glob(os.path.join(chemin_chip, "temp*_input"))):
            cle = os.path.basename(chemin)[: -len("_input")]
            valeur = lire_entier_fichier(chemin, 1000)
            if valeur is None:
                continue
            etiquette = (lire_texte_fichier(os.path.join(chemin_chip, cle + "_label"))
                         or f"Température {cle}")
            critique = lire_entier_fichier(os.path.join(chemin_chip, cle + "_crit"), 1000)
            alarme = lire_texte_fichier(os.path.join(chemin_chip, cle + "_alarm")) == "1"
            ratio = (valeur / critique) if critique else None
            capteurs.append({
                "source": nom_chip,
                "type": "Température",
                "nom": etiquette,
                "valeur": f"{valeur:.1f}",
                "unite": "°C",
                "limite": f"{critique:.0f} °C" if critique else "—",
                "etat": capteur_etat(alarme, ratio),
            })

        for chemin in sorted(glob.glob(os.path.join(chemin_chip, "fan*_input"))):
            cle = os.path.basename(chemin)[: -len("_input")]
            valeur = lire_entier_fichier(chemin)
            if valeur is None:
                continue
            alarme = lire_texte_fichier(os.path.join(chemin_chip, cle + "_alarm")) == "1"
            capteurs.append({
                "source": nom_chip,
                "type": "Ventilateur",
                "nom": lire_texte_fichier(os.path.join(chemin_chip, cle + "_label")) or cle,
                "valeur": f"{valeur:.0f}",
                "unite": "tr/min",
                "limite": "—",
                "etat": capteur_etat(alarme, None),
            })

        for chemin in sorted(glob.glob(os.path.join(chemin_chip, "in*_input"))):
            cle = os.path.basename(chemin)[: -len("_input")]
            valeur = lire_entier_fichier(chemin, 1000)
            if valeur is None:
                continue
            alarme = lire_texte_fichier(os.path.join(chemin_chip, cle + "_alarm")) == "1"
            capteurs.append({
                "source": nom_chip,
                "type": "Tension",
                "nom": lire_texte_fichier(os.path.join(chemin_chip, cle + "_label")) or cle,
                "valeur": f"{valeur:.3f}",
                "unite": "V",
                "limite": "—",
                "etat": capteur_etat(alarme, None),
            })

        for chemin in sorted(glob.glob(os.path.join(chemin_chip, "curr*_input"))):
            cle = os.path.basename(chemin)[: -len("_input")]
            valeur = lire_entier_fichier(chemin, 1000)
            if valeur is None:
                continue
            alarme = lire_texte_fichier(os.path.join(chemin_chip, cle + "_alarm")) == "1"
            capteurs.append({
                "source": nom_chip,
                "type": "Courant",
                "nom": lire_texte_fichier(os.path.join(chemin_chip, cle + "_label")) or cle,
                "valeur": f"{valeur:.3f}",
                "unite": "A",
                "limite": "—",
                "etat": capteur_etat(alarme, None),
            })

        for chemin in sorted(glob.glob(os.path.join(chemin_chip, "power*_input"))):
            cle = os.path.basename(chemin)[: -len("_input")]
            valeur = lire_entier_fichier(chemin, 1000000)
            if valeur is None:
                continue
            alarme = lire_texte_fichier(os.path.join(chemin_chip, cle + "_alarm")) == "1"
            capteurs.append({
                "source": nom_chip,
                "type": "Puissance",
                "nom": lire_texte_fichier(os.path.join(chemin_chip, cle + "_label")) or cle,
                "valeur": f"{valeur:.2f}",
                "unite": "W",
                "limite": "—",
                "etat": capteur_etat(alarme, None),
            })

    return affiner_capteurs_ite(capteurs)


# Libellés et échelles de la puce ITE IT8620E relevés sur les cartes
# Gigabyte série H97 (configurations lm-sensors de référence) :
# canal -> (libellé, ratio de conversion, tension nominale en V)
RAILS_ITE_8620 = {
    "in0": ("CPU Vcore", 1.0, 0.8),
    "in1": ("+3.3V", 1.68, 3.3),
    "in2": ("+12V", 6.0, 12.0),
    "in3": ("+5V", 2.5, 5.0),
    "in4": ("+3.3V", 1.649, 3.3),
    "in5": ("CPU VRIN", 0.99, 1.7),
    "in6": ("VDRAM", 1.0, 1.5),
}


def affiner_capteurs_ite(capteurs):
    """Applique les libellés et ratios de la puce ITE IT8620E (Gigabyte H97).

    Un canal converti n'est étiqueté que si le résultat reste à ±10 % de sa
    tension nominale ; sinon la lecture brute est conservée sous forme
    « inN (brute) ». Retire les sondes non connectées (lecture fantôme
    -128 °C) et neutralise l'état des ventilateurs à l'arrêt.
    """
    resultats = []
    for capteur in capteurs:
        if capteur["type"] == "Température":
            try:
                if float(capteur["valeur"]) <= -55:
                    continue
            except ValueError:
                pass
            resultats.append(capteur)
            continue
        if capteur["type"] == "Tension":
            nom = capteur["nom"]
            definition = RAILS_ITE_8620.get(nom)
            if definition:
                libelle, ratio, nominale = definition
                try:
                    valeur_reelle = float(capteur["valeur"]) * ratio
                except ValueError:
                    resultats.append(capteur)
                    continue
                if abs(valeur_reelle - nominale) <= 0.1 * nominale:
                    capteur["nom"] = libelle
                    capteur["valeur"] = f"{valeur_reelle:.2f}"
                else:
                    capteur["nom"] = f"{nom} (brute)"
            resultats.append(capteur)
            continue
        if capteur["type"] == "Ventilateur":
            if capteur["valeur"] == "0":
                capteur["etat"] = "—"
            elif capteur["nom"] == "fan1":
                capteur["nom"] = "Ventilateur CPU"
        resultats.append(capteur)
    return resultats


def frequences_cpu():
    """Fréquence actuelle (MHz) de chaque cœur logique depuis /proc/cpuinfo."""
    freqs = []
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
            for ligne in f:
                if ligne.lower().startswith("cpu mhz"):
                    try:
                        freqs.append(float(ligne.split(":", 1)[1].strip()))
                    except (ValueError, IndexError):
                        pass
    except OSError:
        pass
    return freqs


def mesures_nvidia(executable="nvidia-smi"):
    """Données GPU NVIDIA via `nvidia-smi` (température, ventilateur,
    charge, mémoire VRAM, puissance du/des GPU). Liste vide si
    nvidia-smi est absent (pas de pilote NVIDIA) ou indisponible."""
    if shutil.which(executable) is None:
        return []
    try:
        res = subprocess.run(
            [executable,
             "--query-gpu=name,temperature.gpu,fan.speed,utilization.gpu,"
             "power.draw,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
    except Exception:
        return []
    capteurs = []
    for i, brut in enumerate(res.stdout.splitlines()):
        champs = [c.strip() for c in brut.split(",")]
        if len(champs) < 7:
            continue
        nom_gpu = champs[0] or f"GPU {i + 1}"
        prefixe = f"GPU NVIDIA — {nom_gpu}"

        try:
            temperature = float(champs[1])
        except (ValueError, TypeError, IndexError):
            pass
        else:
            if temperature > 0:
                capteurs.append({
                    "type": "Température", "nom": prefixe,
                    "valeur": f"{temperature:.0f}", "unite": "°C", "limite": "95",
                    "etat": capteur_etat(temperature >= 85, temperature / 95.0)})

        try:
            ventilo = float(champs[2])
        except (ValueError, TypeError, IndexError):
            pass
        else:
            if ventilo >= 0:
                capteurs.append({
                    "type": "Ventilateur", "nom": prefixe,
                    "valeur": f"{ventilo:.0f}", "unite": "%",
                    "limite": "100", "etat": "OK" if ventilo > 0 else "À surveiller"})

        try:
            charge = float(champs[3])
        except (ValueError, TypeError, IndexError):
            pass
        else:
            if charge >= 0:
                capteurs.append({
                    "type": "Charge", "nom": prefixe,
                    "valeur": f"{charge:.0f}", "unite": "%", "limite": "—",
                    "etat": "À surveiller" if charge >= 95 else "OK"})

        try:
            watts = float(champs[4])
        except (ValueError, TypeError, IndexError):
            pass
        else:
            if watts > 0:
                capteurs.append({
                    "type": "Puissance", "nom": prefixe,
                    "valeur": f"{watts:.1f}", "unite": "W", "limite": "—", "etat": "OK"})

        try:
            vram_utilisee = float(champs[5])
            vram_totale = float(champs[6])
        except (ValueError, TypeError, IndexError):
            pass
        else:
            if vram_totale > 0:
                ratio_vram = vram_utilisee / vram_totale
                capteurs.append({
                    "type": "Mémoire VRAM", "nom": prefixe,
                    "valeur": f"{vram_utilisee:.0f} / {vram_totale:.0f}", "unite": "MiB",
                    "limite": f"{vram_totale:.0f}",
                    "etat": "À surveiller" if ratio_vram >= 0.95 else "OK"})

    return capteurs


MOTIF_CAPTEUR_SENSORS = re.compile(
    r"^(.+?):\s+\+?(-?[\d.]+)\s*(°C|C|RPM|mV|V|A|W)\b")


def capteurs_depuis_sensors(texte=None):
    """Repli : lecture de la commande `sensors` (lm-sensors) pour les
    ventilateurs, tensions, courants et puissances non exposés par hwmon.
    Détectables après configuration par « sudo sensors-detect »."""
    if texte is None:
        if shutil.which("sensors") is None:
            return []
        try:
            res = subprocess.run(["sensors"], capture_output=True, text=True, timeout=10)
        except Exception:
            return []
        texte = res.stdout
    capteurs = []
    puce = ""
    for brut in (texte or "").splitlines():
        ligne = brut.strip()
        if not ligne:
            puce = ""
            continue
        if not brut.startswith((" ", "\t")) and ":" not in ligne:
            puce = ligne
            continue
        m = MOTIF_CAPTEUR_SENSORS.match(ligne)
        if not m:
            continue
        nom, valeur, unite = m.group(1).strip(), float(m.group(2)), m.group(3)
        if unite == "RPM":
            capteurs.append({
                "source": puce or "sensors", "type": "Ventilateur", "nom": nom,
                "valeur": f"{valeur:.0f}", "unite": "tr/min", "limite": "—",
                "etat": "OK" if valeur > 0 else "À surveiller"})
        elif unite in ("V", "mV"):
            if unite == "mV":
                valeur /= 1000
            capteurs.append({
                "source": puce or "sensors", "type": "Tension", "nom": nom,
                "valeur": f"{valeur:.3f}", "unite": "V", "limite": "—", "etat": "OK"})
        elif unite == "A":
            capteurs.append({
                "source": puce or "sensors", "type": "Courant", "nom": nom,
                "valeur": f"{valeur:.3f}", "unite": "A", "limite": "—", "etat": "OK"})
        elif unite == "W":
            capteurs.append({
                "source": puce or "sensors", "type": "Puissance", "nom": nom,
                "valeur": f"{valeur:.2f}", "unite": "W", "limite": "—", "etat": "OK"})
        elif unite in ("°C", "C"):
            capteurs.append({
                "source": puce or "sensors", "type": "Température", "nom": nom,
                "valeur": f"{valeur:.1f}", "unite": "°C", "limite": "—", "etat": "OK"})
    return capteurs


# ============================================================
# KareDiag - Zone 15 (fenêtre) : surveillance des capteurs et
# vitesse du CPU en temps réel (tableau complet + export CSV)
# ============================================================
class KCapteursWindow(QDialog):
    """Zone 15 : mesures en direct des fréquences CPU, de la charge,
    des capteurs de la carte mère (températures, ventilateurs, tensions,
    courants, puissances) et du GPU NVIDIA via nvidia-smi."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KareDiag - Surveillance des capteurs et CPU (Zone 15)")
        self.resize(900, 640)
        self.setMinimumSize(780, 560)

        self.setStyleSheet("""
            QDialog { background-color: #181a1f; }
            QGroupBox {
                color: #00bcd4;
                font-weight: bold;
                font-size: 13px;
                border: 2px solid #3e4451;
                border-radius: 8px;
                margin-top: 12px;
                background-color: rgba(33, 37, 43, 210);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 5px;
            }
            QPushButton {
                background-color: #2188ff;
                color: white;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover { background-color: #006fe6; }
            QPushButton:disabled { background-color: #3b4252; color: #606b7d; }
            QLabel, QComboBox { color: #abb2bf; font-size: 12px; }
            QComboBox {
                background-color: #21252b;
                border: 1px solid #4b5263;
                border-radius: 4px;
                padding: 4px;
            }
        """)

        layout = QVBoxLayout(self)

        titre = QLabel("KareDiag - Surveillance des capteurs et vitesse du CPU (temps réel)")
        titre.setStyleSheet("font-size: 14px; font-weight: bold; color: #00bcd4;")
        titre.setAlignment(Qt.AlignCenter)
        layout.addWidget(titre)

        note = QLabel(
            "Toutes les mesures s'affichent ici sans privilèges : CPU, carte mère et GPU "
            "NVIDIA (si nvidia-smi est installé). Changez l'intervalle de rafraîchissement "
            "à tout moment ; l'export CSV enregistre le dernier instantané affiché."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        layout_z15_ctrl = QHBoxLayout()
        self.btn_capteurs = QPushButton("▶ Démarrer la surveillance")
        self.btn_capteurs.clicked.connect(self.basculer_surveillance_capteurs)

        self.combo_capteurs_intervalle = QComboBox()
        self.combo_capteurs_intervalle.addItems(["1 s", "2 s", "5 s"])

        self.btn_capteurs_export = QPushButton("Exporter (CSV)")
        self.btn_capteurs_export.clicked.connect(self.exporter_capteurs_csv)

        self.lbl_capteurs_etat = QLabel("Surveillance arrêtée — aucune mesure.")
        self.lbl_capteurs_etat.setStyleSheet("color: #606b7d; font-style: italic;")

        layout_z15_ctrl.addWidget(self.btn_capteurs)
        layout_z15_ctrl.addWidget(QLabel("Intervalle :"))
        layout_z15_ctrl.addWidget(self.combo_capteurs_intervalle)
        layout_z15_ctrl.addWidget(self.btn_capteurs_export)
        layout_z15_ctrl.addWidget(self.lbl_capteurs_etat, stretch=1)
        layout.addLayout(layout_z15_ctrl)

        self.table_capteurs = QTableWidget(0, 6)
        self.table_capteurs.setHorizontalHeaderLabels(
            ["Capteur", "Type", "Valeur", "Unité", "Limite", "État"])
        self.table_capteurs.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table_capteurs.horizontalHeader().setStretchLastSection(True)
        self.table_capteurs.verticalHeader().setVisible(False)
        self.table_capteurs.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_capteurs.setSelectionMode(QAbstractItemView.NoSelection)
        self.table_capteurs.setAlternatingRowColors(True)
        self.table_capteurs.setStyleSheet("""
            QTableWidget {
                background-color: #1e1e1e;
                color: #abb2bf;
                border: 1px solid #3e4451;
                border-radius: 4px;
                gridline-color: #3e4451;
                font-size: 11px;
            }
            QHeaderView::section {
                background-color: #21252b;
                color: #00bcd4;
                border: 1px solid #3e4451;
                padding: 4px;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.table_capteurs)

        self.timer_capteurs = QTimer(self)
        self.timer_capteurs.timeout.connect(self.maj_capteurs)
        self.combo_capteurs_intervalle.currentIndexChanged.connect(self.changer_intervalle_capteurs)
        self.cpu_temps_precedent = None

    def intervalle_capteurs_ms(self):
        return [1000, 2000, 5000][self.combo_capteurs_intervalle.currentIndex()]

    def changer_intervalle_capteurs(self):
        if self.timer_capteurs.isActive():
            self.timer_capteurs.start(self.intervalle_capteurs_ms())

    def basculer_surveillance_capteurs(self):
        if self.timer_capteurs.isActive():
            self.timer_capteurs.stop()
            self.btn_capteurs.setText("▶ Démarrer la surveillance")
            self.lbl_capteurs_etat.setText("Surveillance arrêtée.")
            self.lbl_capteurs_etat.setStyleSheet("color: #606b7d; font-style: italic;")
        else:
            self.timer_capteurs.start(self.intervalle_capteurs_ms())
            self.maj_capteurs()

    def temps_cpu(self):
        """(inactif, total) depuis /proc/stat, ou None si indisponible."""
        try:
            with open("/proc/stat", "r", encoding="utf-8") as f:
                valeurs = [int(v) for v in f.readline().split()[1:]]
        except (OSError, ValueError, IndexError):
            return None
        inactif = valeurs[3] + (valeurs[4] if len(valeurs) > 4 else 0)
        return inactif, sum(valeurs)

    def maj_capteurs(self):
        lignes = []

        for i, mhz in enumerate(frequences_cpu()):
            lignes.append((f"CPU cœur {i}", "Fréquence", f"{mhz:.0f}", "MHz", "—", "—"))

        temps = self.temps_cpu()
        if temps and self.cpu_temps_precedent:
            idle_avant, total_avant = self.cpu_temps_precedent
            inactif, total = temps
            allocation = total - total_avant
            if allocation > 0:
                charge = 100.0 * (1.0 - (inactif - idle_avant) / allocation)
                etat_charge = "À surveiller" if charge >= 90 else ("ALERTE" if charge >= 99.5 else "OK")
                lignes.append(("Charge CPU (tous cœurs)", "Charge",
                               f"{charge:.0f}", "%", "—", etat_charge))
        self.cpu_temps_precedent = temps

        capteurs_gpu = mesures_nvidia()
        capteurs = mesures_hwmon()
        types_lus = {c["type"] for c in capteurs}
        repli = capteurs_depuis_sensors()
        if "Ventilateur" not in types_lus:
            capteurs += [c for c in repli if c["type"] == "Ventilateur"]
        if "Tension" not in types_lus:
            capteurs += [c for c in repli if c["type"] == "Tension"]

        conseils = []
        if not any(c["type"] == "Ventilateur" for c in capteurs):
            conseils.append("ventilateurs non détectés — lancez « sudo sensors-detect » puis redémarrez")
        if not any(c["type"] == "Tension" for c in capteurs):
            conseils.append("tensions CPU non exposées par cette carte mère")

        for capteur in capteurs:
            lignes.append((capteur["nom"], capteur["type"], capteur["valeur"],
                           capteur["unite"], capteur["limite"], capteur["etat"]))
        for capteur in capteurs_gpu:
            lignes.append((capteur["nom"], capteur["type"], capteur["valeur"],
                           capteur["unite"], capteur["limite"], capteur["etat"]))

        couleurs_etat = {"OK": "#98c379", "À surveiller": "#e5c07b", "ALERTE": "#e06c75"}
        self.table_capteurs.setRowCount(len(lignes))
        for r, entree in enumerate(lignes):
            for c, contenu in enumerate(entree):
                item = QTableWidgetItem(str(contenu))
                if c == 5 and contenu in couleurs_etat:
                    item.setForeground(QBrush(QColor(couleurs_etat[contenu])))
                    item.setTextAlignment(Qt.AlignCenter)
                self.table_capteurs.setItem(r, c, item)

        texte_etat = (f"Dernière mesure : {datetime.now().strftime('%H:%M:%S')} — "
                      f"{len(frequences_cpu())} cœur(s) CPU, {len(capteurs)} capteur(s) de la carte mère"
                      + (f", {len(capteurs_gpu)} mesure(s) GPU NVIDIA." if capteurs_gpu else "."))
        if conseils:
            texte_etat += "  [i] " + ". ".join(conseils) + "."
        self.lbl_capteurs_etat.setText(texte_etat)
        self.lbl_capteurs_etat.setStyleSheet("color: #98c379; font-style: italic;")

    def exporter_capteurs_csv(self):
        if self.table_capteurs.rowCount() == 0:
            QMessageBox.information(
                self, "Aucune mesure",
                "Démarrez la surveillance pour collecter des mesures avant l'export.")
            return
        chemin, _ = QFileDialog.getSaveFileName(
            self, "Exporter les capteurs (CSV)",
            os.path.join(bureau_utilisateur(),
                         f"karediag_capteurs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"),
            "Fichiers CSV (*.csv)")
        if not chemin:
            return
        try:
            with open(chemin, "w", encoding="utf-8") as f:
                f.write("Capteur;Type;Valeur;Unite;Limite;Etat\n")
                for r in range(self.table_capteurs.rowCount()):
                    valeurs = []
                    for c in range(self.table_capteurs.columnCount()):
                        item = self.table_capteurs.item(r, c)
                        valeurs.append(item.text() if item else "")
                    f.write(";".join(valeurs) + "\n")
            QMessageBox.information(self, "Export réalisé",
                                    f"Les données ont été enregistrées ici :\n{chemin}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur",
                                 f"Erreur lors de l'export :\n{e}")

    def closeEvent(self, event):
        self.timer_capteurs.stop()
        self.btn_capteurs.setText("▶ Démarrer la surveillance")
        self.lbl_capteurs_etat.setText("Surveillance arrêtée.")
        self.lbl_capteurs_etat.setStyleSheet("color: #606b7d; font-style: italic;")
        event.accept()


# KareDiag - Audit global : score de santé, recommandations,
# export HTML, historique (portage corrigé d'OmniAudit)
# ============================================================
HISTORY_DIR = os.path.expanduser("~/.karediag")
HISTORY_FILE = os.path.join(HISTORY_DIR, "audit_history.json")


def audit_run_cmd(command, timeout=10):
    try:
        res = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return res.returncode == 0, res.stdout, res.stderr
    except Exception as e:
        return False, "", str(e)


def audit_smart_status(disque):
    if not disque:
        return "Non vérifié (aucun disque sélectionné dans KareDiag)"
    if not shutil.which("smartctl"):
        return "Inconnu (smartmontools non installé)"
    ok, out, err = audit_run_cmd(prefixe_privilege() + ["smartctl", "-H", disque])
    if "PASSED" in out:
        return "PASSED"
    if "FAILED" in out:
        return "FAILED"
    return "Inconnu (privilèges refusés ou disque non supporté)"


def audit_partitions():
    parts = []
    ok, out, _ = audit_run_cmd(["df", "-Pl"])
    if not ok:
        return parts
    for ligne in out.splitlines()[1:]:
        cols = ligne.split()
        if len(cols) < 6 or not cols[5].startswith("/"):
            continue
        percu = cols[4].rstrip("%")
        if not percu.isdigit():
            continue
        if cols[0].startswith((("/dev/loop", "tmpfs", "udev", "overlay", "squashfs"))):
            continue
        parts.append({"mountpoint": cols[5], "filesystem": cols[0], "percent_used": int(percu)})
    return parts


def audit_secure_boot():
    if not os.path.exists("/sys/firmware/efi"):
        return {"mode": "Legacy (BIOS)", "secure_boot": None}
    efi_path = "/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
    if os.path.exists(efi_path):
        try:
            with open(efi_path, "rb") as f:
                data = f.read()
            return {"mode": "UEFI", "secure_boot": len(data) >= 5 and data[4] == 1}
        except PermissionError:
            return {"mode": "UEFI", "secure_boot": None}
    return {"mode": "UEFI", "secure_boot": None}


def audit_ram():
    try:
        with open("/proc/meminfo", "r") as f:
            info = {}
            for ligne in f:
                cle, val = ligne.split(":", 1)
                info[cle.strip()] = int(val.strip().split()[0])
        total = info.get("MemTotal", 0)
        dispo = info.get("MemAvailable", 0)
        return {
            "total_gb": round(total / 1024**2, 2),
            "available_gb": round(dispo / 1024**2, 2),
            "percent_used": round(100 * (total - dispo) / total, 1) if total else 0,
        }
    except Exception:
        return {"total_gb": "N/A", "available_gb": "N/A", "percent_used": "N/A"}


def audit_failed_services():
    if not shutil.which("systemctl"):
        return {"count": 0, "services": [], "status": "systemd non disponible"}
    ok, out, _ = audit_run_cmd(["systemctl", "list-units", "--state=failed", "--no-legend", "--no-pager"])
    services = [l.split()[0] for l in out.splitlines() if l.strip()] if ok else []
    return {"count": len(services), "services": services, "status": "Analysé"}


def audit_firewall():
    if shutil.which("ufw"):
        ok, out, _ = audit_run_cmd(
            prefixe_privilege() + ["env", "LC_ALL=C", "ufw", "status"]
        )
        if ok and "Status:" in out:
            return {"installed": True, "active": "Status: active" in out, "name": "ufw"}
        actif, _, _ = audit_run_cmd(["systemctl", "is-active", "ufw"])
        return {"installed": True, "active": actif, "name": "ufw"}
    if shutil.which("firewall-cmd"):
        ok, out, _ = audit_run_cmd(prefixe_privilege() + ["firewall-cmd", "--state"])
        if ok and out.strip():
            return {"installed": True, "active": out.strip() == "running", "name": "firewalld"}
        actif, _, _ = audit_run_cmd(["systemctl", "is-active", "firewalld"])
        return {"installed": True, "active": actif, "name": "firewalld"}
    return {"installed": False, "active": False, "name": None}


def audit_ssh_root_login():
    chemins = sorted(glob.glob("/etc/ssh/sshd_config.d/*.conf")) + ["/etc/ssh/sshd_config"]
    if not any(os.path.exists(c) for c in chemins):
        return {"status": "SSH non installé", "permit_root_login": "Inconnu"}
    for chemin in chemins:
        if not os.path.exists(chemin):
            continue
        try:
            with open(chemin, "r") as f:
                for ligne in f:
                    ligne = ligne.strip()
                    if not ligne or ligne.startswith("#"):
                        continue
                    parts = ligne.split()
                    if len(parts) >= 2 and parts[0].lower() == "permitrootlogin":
                        return {"status": "Analysé", "permit_root_login": parts[1].lower(), "source": chemin}
        except Exception:
            continue
    return {"status": "Analysé", "permit_root_login": "Non spécifié"}


def audit_uid_zero():
    users = []
    try:
        with open("/etc/passwd", "r") as f:
            for ligne in f:
                parts = ligne.strip().split(":")
                if len(parts) >= 3 and parts[2] == "0":
                    users.append(parts[0])
    except Exception:
        return {"status": "Erreur", "root_users": []}
    return {"status": "Analysé", "root_users": users}


def audit_ports():
    ok, out, _ = audit_run_cmd(["ss", "-tuln"])
    if not ok:
        return {"status": "Non disponible", "ports": []}
    ports = []
    for ligne in out.splitlines():
        cols = ligne.split()
        if len(cols) >= 5 and cols[0] in ("tcp", "udp"):
            if (cols[0] == "tcp" and "LISTEN" in ligne) or (cols[0] == "udp" and "UNCONN" in ligne):
                ports.append({"protocol": cols[0].upper(), "address": cols[4]})
    return {"status": "Analysé", "ports": ports}


def audit_analyser(hw, sw):
    score = 100
    recs = []

    bios = hw["bios"]
    if bios["mode"] == "UEFI" and bios["secure_boot"] is False:
        score -= 15
        recs.append({"category": "Sécurité / BIOS", "level": "warning",
                     "title": "Secure Boot désactivé",
                     "description": "Le Secure Boot est désactivé dans l'UEFI.",
                     "action": "Activer le Secure Boot dans le BIOS/UEFI."})

    smart = hw["smart_status"]
    if "FAILED" in smart:
        score -= 40
        recs.append({"category": "Matériel / Stockage", "level": "critical",
                     "title": "Défaillance disque imminente (S.M.A.R.T)",
                     "description": f"État : {smart}",
                     "action": "Sauvegarder et remplacer le disque d'urgence."})
    elif "non installé" in smart:
        recs.append({"category": "Matériel / Stockage", "level": "warning",
                     "title": "Santé SMART non vérifiable",
                     "description": "smartmontools n'est pas installé.",
                     "action": "Installer smartmontools : sudo apt install smartmontools"})

    for p in hw["partitions"]:
        if p["percent_used"] > 90:
            score -= 20
            recs.append({"category": "Performance / Stockage", "level": "critical",
                         "title": f"Espace disque critique sur {p['mountpoint']}",
                         "description": f"Rempli à {p['percent_used']}% ({p['filesystem']})",
                         "action": "Nettoyer les caches et fichiers temporaires."})

    failed = sw["failed_services"]
    if failed["count"] > 0:
        score -= min(20, 5 * failed["count"])
        recs.append({"category": "Logiciel / Système", "level": "warning",
                     "title": f"{failed['count']} service(s) systemd en échec",
                     "description": f"Services : {', '.join(failed['services'])}",
                     "action": "Vérifier avec : systemctl status <service>"})

    fw = sw["firewall"]
    if not fw["installed"]:
        score -= 10
        recs.append({"category": "Sécurité / Réseau", "level": "warning",
                     "title": "Aucun pare-feu détecté",
                     "description": "Ni UFW ni firewalld ne sont installés.",
                     "action": "Installer et activer un pare-feu : sudo apt install ufw && sudo ufw enable"})
    elif not fw["active"]:
        score -= 15
        recs.append({"category": "Sécurité / Réseau", "level": "warning",
                     "title": f"Pare-feu {fw['name']} inactif",
                     "description": f"{fw['name']} est installé mais désactivé.",
                     "action": f"Activer avec : sudo {fw['name']} enable"})

    ssh = sw["ssh"]
    if ssh["permit_root_login"] == "yes":
        score -= 15
        recs.append({"category": "Sécurité / SSH", "level": "warning",
                     "title": "Connexion root SSH autorisée",
                     "description": f"PermitRootLogin yes détecté ({ssh.get('source', 'sshd_config')}).",
                     "action": "Définir PermitRootLogin no dans la configuration SSH."})

    uid_zero = sw["uid_zero"]["root_users"]
    if len(uid_zero) > 1:
        score -= 40
        recs.append({"category": "Sécurité / Utilisateurs", "level": "critical",
                     "title": "Plusieurs comptes avec les privilèges root (UID 0)",
                     "description": f"Comptes UID 0 détectés : {', '.join(uid_zero)}",
                     "action": "Vérifier et supprimer les comptes non autorisés."})

    score = max(0, min(100, score))
    return {"score": score, "recommendations": recs}


def audit_sauver_historique(score, nb_critiques, nb_avertissements, fichier=None):
    os.makedirs(HISTORY_DIR, exist_ok=True)
    hist = audit_charger_historique()
    hist.append({"date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "score": score, "critiques": nb_critiques,
                 "avertissements": nb_avertissements, "fichier": fichier})
    hist = hist[-50:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(hist, f, indent=2, ensure_ascii=False)
    audit_nettoyer_rapports()


def audit_charger_historique():
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


# ============================================================
# KareDiag - Zone 10 : comparaison de rapports d'audit
# ============================================================
AUDITS_DIR = os.path.join(HISTORY_DIR, "audits")


def audit_sauver_rapport_complet(resultat):
    """Archive le rapport d'audit complet (recommandations incluses).

    Alimente la comparaison avant/après de la Zone 10.
    Renvoie le chemin du fichier JSON créé."""
    os.makedirs(AUDITS_DIR, exist_ok=True)
    chemin = os.path.join(
        AUDITS_DIR,
        f"audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(resultat, f, indent=2, ensure_ascii=False)
    return chemin


def audit_charger_rapport(chemin):
    """Charge un rapport d'audit complet ; None si absent ou illisible."""
    if not chemin or not os.path.isfile(chemin):
        return None
    try:
        with open(chemin, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def audit_nettoyer_rapports():
    """Supprime les rapports complets orphelins (absents de l'historique)."""
    try:
        gardes = {e.get("fichier") for e in audit_charger_historique()}
        for chemin in glob.glob(os.path.join(AUDITS_DIR, "audit_*.json")):
            if chemin not in gardes:
                os.remove(chemin)
    except Exception:
        pass


def couleur_score_audit(score):
    """Couleur standardisée de l'affichage du score /100."""
    if score >= 80:
        return "#98c379"
    if score >= 50:
        return "#e5c07b"
    return "#e06c75"


# ============================================================
# KareDiag - Utilitaires communs (Zones 3 et 4)
# ============================================================
def lister_blocs():
    """Liste les disques et partitions : [{"nom", "type", "taille", "parent", "affichage"}]."""
    entrees = []
    try:
        res = subprocess.run(
            ["lsblk", "-b", "-o", "NAME,TYPE,SIZE,ROTA,MODEL,SERIAL,MOUNTPOINT", "--json"],
            capture_output=True, text=True, check=True
        )
        data = json.loads(res.stdout)

        def ajouter(noeud, parent=None):
            nom_bas = noeud.get("name", "")
            if not nom_bas:
                return
            nom = f"/dev/{nom_bas}"
            typ = noeud.get("type", "")
            taille = noeud.get("size")
            if isinstance(taille, int) and taille > 0:
                if taille >= 1024 ** 3:
                    taille_str = f"{taille / 1024**3:.2f} Go"
                else:
                    taille_str = f"{max(1, round(taille / 1024**2))} Mo"
            else:
                taille_str = "taille inconnue"
            if typ == "disk":
                rota = noeud.get("rota")
                type_disque = "SSD" if rota is False else "HDD" if rota is True else "Type inconnu"
                modele = (noeud.get("model") or "Modèle inconnu").strip()
                serial = (noeud.get("serial") or "S/N inconnu").strip()
                affichage = f"{nom} — {modele} ({type_disque}) [S/N: {serial}] — {taille_str}"
                entrees.append({"nom": nom, "type": "disk", "taille": taille, "parent": None, "affichage": affichage})
            elif typ == "part":
                point = noeud.get("mountpoint")
                suffixe = f" (montée : {point})" if point else ""
                affichage = f"{nom} — partition de {parent}{suffixe} — {taille_str}"
                entrees.append({"nom": nom, "type": "part", "taille": taille, "parent": parent, "affichage": affichage})
            for enfant in noeud.get("children", []) or []:
                ajouter(enfant, nom if typ == "disk" else parent)

        for disque in data.get("blockdevices", []):
            ajouter(disque)
    except Exception:
        pass
    return entrees


def disque_parent(chemin_bloc):
    try:
        res = subprocess.run(["lsblk", "-rno", "PKNAME", chemin_bloc], capture_output=True, text=True)
        nom = res.stdout.strip().splitlines()[0].strip() if res.stdout.strip() else ""
        return f"/dev/{nom}" if nom else None
    except Exception:
        return None


def device_contient_systeme(chemin):
    try:
        res = subprocess.run(
            ["lsblk", "-rno", "MOUNTPOINT", chemin],
            capture_output=True, text=True
        )
        return "/" in [l.strip() for l in res.stdout.splitlines() if l.strip()]
    except Exception:
        return False


def demonter_chemin(chemin_part, log_fn=None):
    erreurs = []
    r = None
    for _ in range(3):
        r = subprocess.run(
            prefixe_privilege() + ["umount", chemin_part],
            capture_output=True, text=True
        )
        if r.returncode == 0:
            break
    if r is None or r.returncode != 0:
        erreurs.append(f"umount {chemin_part} : " + (r.stderr.strip() if r else "échec"))
    elif log_fn:
        log_fn(f"{chemin_part} démonté")
    return erreurs


def demonter_destination(chemin, log_fn=None):
    """Démonte les partitions et désactive le swap du disque ou de la partition cible.

    Renvoie la liste des erreurs (vide si tout est démonté proprement).
    """
    erreurs = []
    try:
        res = subprocess.run(
            ["lsblk", "-rno", "NAME,MOUNTPOINT", chemin],
            capture_output=True, text=True
        )
        for ligne in res.stdout.splitlines():
            parties = ligne.split(None, 1)
            if len(parties) < 2:
                continue
            chemin_part = f"/dev/{parties[0]}"
            point = parties[1].strip()
            if point == "[SWAP]":
                r = subprocess.run(
                    prefixe_privilege() + ["swapoff", chemin_part],
                    capture_output=True, text=True
                )
                if r.returncode != 0:
                    erreurs.append(f"swapoff {chemin_part} : {r.stderr.strip()}")
                elif log_fn:
                    log_fn(f"Swap désactivé sur {chemin_part}")
            elif point:
                erreurs.extend(demonter_chemin(chemin_part, log_fn))
        subprocess.run(["udevadm", "settle"], capture_output=True, text=True, timeout=30)
    except Exception as e:
        erreurs.append(str(e))
    return erreurs


# ============================================================
# KareDiag - Fenêtre d'audit global (Zone 9)
# ============================================================
class KAuditWindow(QDialog):
    """Zone 9 : audit global de la machine.
    Score de santé /100, recommandations classées par niveau de gravité,
    synthèse matériel / logiciel / sécurité, export HTML et historique."""

    NIVEAUX = {
        "critical": ("CRITIQUE", "#e06c75"),
        "warning": ("Avertissement", "#e5c07b"),
    }

    def __init__(self, parent=None, disque_courant=None):
        super().__init__(parent)
        self.setWindowTitle("KareDiag - Audit global de la machine (Zone 9)")
        self.resize(880, 760)
        self.setMinimumSize(780, 660)
        self.disque_courant = disque_courant
        self.resultat_audit = None

        self.setStyleSheet("""
            QDialog { background-color: #181a1f; }
            QGroupBox {
                color: #00bcd4; font-weight: bold; font-size: 13px;
                border: 2px solid #3e4451; border-radius: 8px;
                margin-top: 12px; background-color: rgba(33, 37, 43, 210);
            }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
            QPushButton {
                background-color: #2188ff; color: white; border-radius: 4px;
                padding: 6px 12px; font-weight: bold; border: none;
            }
            QPushButton:hover { background-color: #006fe6; }
            QPushButton:disabled { background-color: #3b4252; color: #606b7d; }
            QLabel { color: #abb2bf; font-size: 12px; }
            QTableWidget {
                background-color: #121417; color: #abb2bf;
                border: 1px solid #3e4451; border-radius: 4px;
                gridline-color: #3e4451;
            }
            QHeaderView::section {
                background-color: #21252b; color: #00bcd4;
                border: none; padding: 4px; font-weight: bold;
            }
            QTextEdit {
                background-color: #121417; color: #00ff00;
                font-family: monospace; font-size: 10px;
                border: 1px solid #3e4451; border-radius: 4px;
            }
            QProgressBar {
                background-color: #21252b; border: 1px solid #3e4451;
                border-radius: 6px; color: #abb2bf; text-align: center;
                font-weight: bold; min-height: 24px;
            }
            QProgressBar::chunk { border-radius: 5px; }
        """)

        layout = QVBoxLayout(self)

        titre = QLabel("Zone 9 - Audit global de la machine")
        titre.setStyleSheet("font-size: 14px; font-weight: bold; color: #00bcd4;")
        titre.setAlignment(Qt.AlignCenter)
        layout.addWidget(titre)

        note = QLabel(
            "Analyse du matériel, du logiciel et de la sécurité de la machine.\n"
            "Score sur 100 : chaque anomalie détectée retire des points et génère une recommandation."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        row_btns = QHBoxLayout()
        self.btn_lancer = QPushButton("🩺 Lancer l'audit")
        self.btn_lancer.clicked.connect(self.lancer_audit)
        self.btn_export_html = QPushButton("🌐 Exporter le rapport (HTML)")
        self.btn_export_html.setEnabled(False)
        self.btn_export_html.clicked.connect(self.exporter_html)
        row_btns.addWidget(self.btn_lancer)
        row_btns.addWidget(self.btn_export_html)
        row_btns.addStretch(1)
        layout.addLayout(row_btns)

        groupe_score = QGroupBox(" Score de santé ")
        lay_score = QHBoxLayout(groupe_score)

        self.lbl_score = QLabel("—")
        self.lbl_score.setFixedWidth(140)
        self.lbl_score.setAlignment(Qt.AlignCenter)
        self.lbl_score.setStyleSheet("font-size: 42px; font-weight: bold; color: #606b7d;")
        lay_score.addWidget(self.lbl_score)

        col_score = QVBoxLayout()
        self.barre_score = QProgressBar()
        self.barre_score.setRange(0, 100)
        self.barre_score.setValue(0)
        self.barre_score.setFormat("%v / 100")
        self.lbl_verdict = QLabel("Aucun audit effectué — cliquez sur « Lancer l'audit ».")
        self.lbl_verdict.setStyleSheet("font-weight: bold; color: #abb2bf;")
        self.lbl_verdict.setWordWrap(True)
        col_score.addWidget(self.barre_score)
        col_score.addWidget(self.lbl_verdict)
        lay_score.addLayout(col_score, stretch=1)

        layout.addWidget(groupe_score)

        groupe_synthese = QGroupBox(" Synthèse du système ")
        lay_synthese = QVBoxLayout(groupe_synthese)
        self.txt_synthese = QTextEdit()
        self.txt_synthese.setReadOnly(True)
        self.txt_synthese.setMinimumHeight(140)
        self.txt_synthese.setPlainText(
            "Matériel     : (non audité)\n"
            "Système      : (non audité)\n"
            "Sécurité     : (non audité)"
        )
        lay_synthese.addWidget(self.txt_synthese)
        layout.addWidget(groupe_synthese)

        groupe_recs = QGroupBox(" Recommandations ")
        lay_recs = QVBoxLayout(groupe_recs)
        self.table_recs = QTableWidget(0, 4)
        self.table_recs.setHorizontalHeaderLabels(["Niveau", "Catégorie", "Constat", "Action recommandée"])
        self.table_recs.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table_recs.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table_recs.setColumnWidth(0, 115)
        self.table_recs.setColumnWidth(1, 160)
        self.table_recs.verticalHeader().setVisible(False)
        self.table_recs.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_recs.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_recs.setWordWrap(True)
        self.table_recs.setAlternatingRowColors(True)
        lay_recs.addWidget(self.table_recs)
        layout.addWidget(groupe_recs, stretch=1)

        groupe_hist = QGroupBox(" Historique des audits (10 derniers sur 50, ~/.karediag) ")
        lay_hist = QVBoxLayout(groupe_hist)
        self.txt_historique = QTextEdit()
        self.txt_historique.setReadOnly(True)
        self.txt_historique.setMinimumHeight(90)
        lay_hist.addWidget(self.txt_historique)
        layout.addWidget(groupe_hist)

        self.afficher_historique()

    def lancer_audit(self):
        self.btn_lancer.setEnabled(False)
        self.btn_export_html.setEnabled(False)
        self.lbl_verdict.setText("Audit en cours...")
        self.lbl_verdict.setStyleSheet("font-weight: bold; color: #e5c07b;")
        QApplication.processEvents()
        try:
            hw = {
                "bios": audit_secure_boot(),
                "smart_status": audit_smart_status(self.disque_courant),
                "partitions": audit_partitions(),
                "ram": audit_ram(),
            }
            sw = {
                "failed_services": audit_failed_services(),
                "firewall": audit_firewall(),
                "ssh": audit_ssh_root_login(),
                "uid_zero": audit_uid_zero(),
                "ports": audit_ports(),
            }
            resultat = audit_analyser(hw, sw)
            resultat["hw"] = hw
            resultat["sw"] = sw
            resultat["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            resultat["disque"] = self.disque_courant
            self.resultat_audit = resultat

            nb_critiques = sum(1 for r in resultat["recommendations"] if r["level"] == "critical")
            nb_avertissements = sum(1 for r in resultat["recommendations"] if r["level"] == "warning")
            try:
                chemin_rapport = audit_sauver_rapport_complet(resultat)
                audit_sauver_historique(resultat["score"], nb_critiques,
                                        nb_avertissements, chemin_rapport)
            except Exception:
                pass

            self.afficher_resultat()
        except Exception as e:
            QMessageBox.critical(self, "Erreur d'audit", f"L'audit a échoué :\n{e}")
        finally:
            self.btn_lancer.setEnabled(True)

    def couleur_score(self, score):
        if score >= 80:
            return "#98c379"
        if score >= 50:
            return "#e5c07b"
        return "#e06c75"

    def afficher_resultat(self):
        if not self.resultat_audit:
            return
        score = self.resultat_audit["score"]
        recs = self.resultat_audit["recommendations"]
        nb_critiques = sum(1 for r in recs if r["level"] == "critical")
        nb_avertissements = sum(1 for r in recs if r["level"] == "warning")
        couleur = self.couleur_score(score)

        self.lbl_score.setText(str(score))
        self.lbl_score.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {couleur};")
        self.barre_score.setValue(score)
        self.barre_score.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {couleur}; border-radius: 5px; }}"
        )

        if nb_critiques:
            verdict = (f"État PRÉOCCUPANT : {nb_critiques} problème(s) critique(s) et "
                       f"{nb_avertissements} avertissement(s). Agissez sans tarder.")
        elif nb_avertissements:
            verdict = (f"État CORRECT : aucun problème critique, mais {nb_avertissements} "
                       "avertissement(s) méritent votre attention.")
        else:
            verdict = "État EXCELLENT : aucune anomalie détectée par l'audit."
        self.lbl_verdict.setText(verdict)
        self.lbl_verdict.setStyleSheet(f"font-weight: bold; color: {couleur};")

        hw = self.resultat_audit["hw"]
        sw = self.resultat_audit["sw"]

        bios = hw["bios"]
        secure_boot = ("activé" if bios["secure_boot"] else
                       "désactivé" if bios["secure_boot"] is False else "inconnu")
        ram = hw["ram"]
        ram_str = ("N/A" if ram["total_gb"] == "N/A"
                   else f"{ram['available_gb']} Go libres / {ram['total_gb']} Go ({ram['percent_used']}% utilisée)")

        partitions = hw["partitions"]
        encombrement = ("Aucune partition montée détectée" if not partitions
                        else " | ".join(f"{p['mountpoint']} à {p['percent_used']}%" for p in partitions))

        failed = sw["failed_services"]
        fw = sw["firewall"]
        ssh = sw["ssh"]
        uid0 = sw["uid_zero"]
        ports = sw["ports"]
        firewall_str = ("aucun pare-feu installé" if not fw["installed"]
                        else f"{fw['name']} ({'actif' if fw['active'] else 'INACTIF'})")

        self.txt_synthese.setPlainText(
            f"Matériel     : Firmware {bios['mode']} | Secure Boot : {secure_boot}\n"
            f"               SMART disque : {hw['smart_status']}\n"
            f"               RAM : {ram_str}\n"
            f"               Partitions : {encombrement}\n"
            f"Système      : Services systemd en échec : {failed['count']}\n"
            f"               Ports en écoute : {len(ports['ports'])}\n"
            f"Sécurité     : Pare-feu : {firewall_str}\n"
            f"               Connexion root SSH : {ssh['permit_root_login']} ({ssh['status']})\n"
            f"               Comptes UID 0 : {', '.join(uid0['root_users']) or 'aucun'}"
        )

        self.table_recs.setRowCount(0)
        for r in recs:
            libelle, _ = self.NIVEAUX.get(r["level"], (r["level"], "#abb2bf"))
            ligne = self.table_recs.rowCount()
            self.table_recs.insertRow(ligne)
            self.table_recs.setItem(ligne, 0, QTableWidgetItem(libelle))
            for colonne, texte in enumerate((r["category"], r["title"], r["action"]), start=1):
                self.table_recs.setItem(ligne, colonne, QTableWidgetItem(texte))
        self.table_recs.resizeRowsToContents()

        self.btn_export_html.setEnabled(True)
        self.afficher_historique()

    def afficher_historique(self):
        hist = audit_charger_historique()
        if not hist:
            self.txt_historique.setPlainText("(aucun audit enregistré)")
            return
        lignes = []
        for h in hist[-10:]:
            lignes.append(
                f"{h.get('date', '?')}   Score {h.get('score', '?'):>3}/100   "
                f"{h.get('critiques', 0)} critique(s), {h.get('avertissements', 0)} avertissement(s)"
            )
        self.txt_historique.setPlainText("\n".join(lignes))

    def exporter_html(self):
        if not self.resultat_audit:
            return
        try:
            r = self.resultat_audit
            score = r["score"]
            couleur = self.couleur_score(score)
            recs_html = ""
            for item in r["recommendations"]:
                libelle, couleur_niveau = self.NIVEAUX.get(item["level"], (item["level"], "#abb2bf"))
                recs_html += f"""
                <tr>
                  <td style="color:{couleur_niveau};font-weight:bold;white-space:nowrap;">{libelle}</td>
                  <td>{item['category']}</td>
                  <td><b>{item['title']}</b><br/>{item['description']}</td>
                  <td>{item['action']}</td>
                </tr>"""
            if not r["recommendations"]:
                recs_html = ('<tr><td colspan="4" style="color:#98c379;text-align:center;">'
                             "Aucune anomalie détectée</td></tr>")

            hw = r["hw"]
            sw = r["sw"]
            secure_boot = ("activé" if hw["bios"]["secure_boot"]
                           else "désactivé" if hw["bios"]["secure_boot"] is False else "inconnu")
            ram = hw["ram"]
            ram_str = ("N/A" if ram["total_gb"] == "N/A"
                       else f"{ram['available_gb']} Go libres / {ram['total_gb']} Go")
            partitions = hw["partitions"]
            partitions_str = ("aucune" if not partitions
                              else "<br/>".join(
                                  f"{p['mountpoint']} : {p['percent_used']}% ({p['filesystem']})"
                                  for p in partitions))
            fw = sw["firewall"]
            firewall_str = ("aucun" if not fw["installed"]
                            else f"{fw['name']} ({'actif' if fw['active'] else 'inactif'})")
            detail = f"""
            <table>
              <tr><th>Élément</th><th>Valeur</th></tr>
              <tr><td>Firmware</td><td>{hw['bios']['mode']} (Secure Boot : {secure_boot})</td></tr>
              <tr><td>SMART disque</td><td>{hw['smart_status']}</td></tr>
              <tr><td>RAM</td><td>{ram_str}</td></tr>
              <tr><td>Partitions</td><td>{partitions_str}</td></tr>
              <tr><td>Services en échec</td><td>{sw['failed_services']['count']}</td></tr>
              <tr><td>Pare-feu</td><td>{firewall_str}</td></tr>
              <tr><td>Connexion root via SSH</td><td>{sw['ssh']['permit_root_login']}</td></tr>
              <tr><td>Comptes UID 0</td><td>{', '.join(sw['uid_zero']['root_users']) or 'aucun'}</td></tr>
              <tr><td>Ports en écoute</td><td>{len(sw['ports']['ports'])}</td></tr>
            </table>"""

            html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8"/>
<title>Rapport d'audit KareDiag</title>
<style>
  body {{ background-color:#181a1f; color:#abb2bf; font-family:sans-serif; margin:2em; }}
  h1, h2 {{ color:#00bcd4; }}
  .score {{ font-size:3em; font-weight:bold; color:{couleur}; }}
  table {{ border-collapse:collapse; width:100%; margin-top:1em; }}
  th, td {{ border:1px solid #3e4451; padding:6px 10px; text-align:left; vertical-align:top; }}
  th {{ background-color:#21252b; color:#00bcd4; }}
  .meta {{ color:#606b7d; font-size:0.9em; }}
</style>
</head>
<body>
<h1>Rapport d'audit KareDiag</h1>
<p class="meta">Édité le {r['timestamp']} — Disque cible : {r['disque'] or 'aucun'}</p>
<p>Score de santé : <span class="score">{score}/100</span></p>
<h2>Synthèse</h2>
{detail}
<h2>Recommandations</h2>
<table>
  <tr><th>Niveau</th><th>Catégorie</th><th>Constat</th><th>Action</th></tr>
{recs_html}
</table>
</body>
</html>"""

            chemin = os.path.join(
                bureau_utilisateur(),
                f"karediag_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            )
            with open(chemin, "w", encoding="utf-8") as f:
                f.write(html)
            QMessageBox.information(
                self, "Rapport exporté",
                f"Le rapport HTML a été enregistré ici :\n{chemin}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Erreur lors de l'export HTML :\n{e}")


class KAuditCompareWindow(QDialog):
    """Zone 10 : comparaison de deux rapports d'audit (avant / après).

    Évolution du score /100, tendance des derniers audits et diff des
    recommandations (résolues / apparues / persistantes), export HTML."""

    STATUTS = {
        "resolue": ("🟢 RÉSOLUE",),
        "apparue": ("🔴 APPARUE",),
        "persistante": ("🟡 PERSISTANTE",),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KareDiag - Comparaison de rapports d'audit (Zone 10)")
        self.resize(920, 780)
        self.setMinimumSize(820, 660)
        self.audits = []
        self.resultat_compare = None

        self.setStyleSheet("""
            QDialog { background-color: #181a1f; }
            QGroupBox {
                color: #00bcd4; font-weight: bold; font-size: 13px;
                border: 2px solid #3e4451; border-radius: 8px;
                margin-top: 12px; background-color: rgba(33, 37, 43, 210);
            }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
            QPushButton {
                background-color: #2188ff; color: white; border-radius: 4px;
                padding: 6px 12px; font-weight: bold; border: none;
            }
            QPushButton:hover { background-color: #006fe6; }
            QPushButton:disabled { background-color: #3b4252; color: #606b7d; }
            QLabel { color: #abb2bf; font-size: 12px; }
            QComboBox, QLineEdit {
                background-color: #21252b; border: 1px solid #4b5263;
                border-radius: 4px; padding: 4px; color: #abb2bf;
            }
            QTableWidget {
                background-color: #121417; color: #abb2bf;
                border: 1px solid #3e4451; border-radius: 4px;
                gridline-color: #3e4451;
            }
            QHeaderView::section {
                background-color: #21252b; color: #00bcd4;
                border: none; padding: 4px; font-weight: bold;
            }
            QTextEdit {
                background-color: #121417; color: #00ff00;
                font-family: monospace; font-size: 10px;
                border: 1px solid #3e4451; border-radius: 4px;
            }
            QProgressBar {
                background-color: #21252b; border: 1px solid #3e4451;
                border-radius: 6px; color: #abb2bf; text-align: center;
                font-weight: bold; min-height: 22px;
            }
            QProgressBar::chunk { border-radius: 5px; }
        """)

        layout = QVBoxLayout(self)

        titre = QLabel("Zone 10 - Comparaison de rapports d'audit")
        titre.setStyleSheet("font-size: 14px; font-weight: bold; color: #00bcd4;")
        titre.setAlignment(Qt.AlignCenter)
        layout.addWidget(titre)

        note = QLabel(
            "Compare deux audits enregistrés par la Zone 9 : évolution du score et diff des recommandations.\n"
            "Lancez au moins deux audits dans la Zone 9 pour pouvoir les comparer."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        groupe_choix = QGroupBox(" Audits à comparer ")
        grille = QGridLayout(groupe_choix)

        self.combo_avant = QComboBox()
        self.combo_avant.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo_apres = QComboBox()
        self.combo_apres.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_comparer = QPushButton("🔎 Comparer")
        self.btn_comparer.clicked.connect(self.comparer)
        self.btn_export_html = QPushButton("🌐 Exporter la comparaison (HTML)")
        self.btn_export_html.setEnabled(False)
        self.btn_export_html.clicked.connect(self.exporter_comparaison)

        grille.addWidget(QLabel("Audit A (avant) :"), 0, 0)
        grille.addWidget(self.combo_avant, 0, 1)
        grille.addWidget(QLabel("Audit B (après) :"), 1, 0)
        grille.addWidget(self.combo_apres, 1, 1)
        grille.addWidget(self.btn_comparer, 0, 2)
        grille.addWidget(self.btn_export_html, 1, 2)
        layout.addWidget(groupe_choix)

        groupe_score = QGroupBox(" Évolution du score ")
        lay_score = QGridLayout(groupe_score)

        self.lbl_titre_a = QLabel("Audit A — (non sélectionné)")
        self.lbl_titre_a.setStyleSheet("font-weight: bold; color: #00bcd4;")
        self.lbl_titre_b = QLabel("Audit B — (non sélectionné)")
        self.lbl_titre_b.setStyleSheet("font-weight: bold; color: #00bcd4;")
        self.lbl_score_a = QLabel("—")
        self.lbl_score_a.setAlignment(Qt.AlignCenter)
        self.lbl_score_a.setStyleSheet("font-size: 34px; font-weight: bold; color: #606b7d;")
        self.lbl_score_b = QLabel("—")
        self.lbl_score_b.setAlignment(Qt.AlignCenter)
        self.lbl_score_b.setStyleSheet("font-size: 34px; font-weight: bold; color: #606b7d;")
        self.barre_a = QProgressBar()
        self.barre_a.setRange(0, 100)
        self.barre_a.setFormat("%v / 100")
        self.barre_b = QProgressBar()
        self.barre_b.setRange(0, 100)
        self.barre_b.setFormat("%v / 100")
        fleche = QLabel("▶")
        fleche.setAlignment(Qt.AlignCenter)
        fleche.setStyleSheet("font-size: 18px; color: #abb2bf;")
        self.lbl_delta = QLabel("")
        self.lbl_delta.setAlignment(Qt.AlignCenter)

        lay_score.addWidget(self.lbl_titre_a, 0, 0)
        lay_score.addWidget(self.lbl_score_a, 1, 0)
        lay_score.addWidget(self.barre_a, 2, 0)
        lay_score.addWidget(fleche, 1, 1)
        lay_score.addWidget(self.lbl_titre_b, 0, 2)
        lay_score.addWidget(self.lbl_score_b, 1, 2)
        lay_score.addWidget(self.barre_b, 2, 2)
        lay_score.addWidget(self.lbl_delta, 1, 3)
        layout.addWidget(groupe_score)

        groupe_tendance = QGroupBox(" Tendance des scores (du plus ancien au plus récent) ")
        lay_tendance = QVBoxLayout(groupe_tendance)
        self.txt_tendance = QTextEdit()
        self.txt_tendance.setReadOnly(True)
        self.txt_tendance.setMinimumHeight(70)
        lay_tendance.addWidget(self.txt_tendance)
        layout.addWidget(groupe_tendance)

        groupe_diff = QGroupBox(" Recommandations : diff A → B ")
        lay_diff = QVBoxLayout(groupe_diff)
        self.table_diff = QTableWidget(0, 4)
        self.table_diff.setHorizontalHeaderLabels(["Statut", "Niveau", "Constat", "Action recommandée"])
        self.table_diff.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table_diff.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table_diff.setColumnWidth(0, 150)
        self.table_diff.setColumnWidth(1, 90)
        self.table_diff.verticalHeader().setVisible(False)
        self.table_diff.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_diff.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_diff.setWordWrap(True)
        self.table_diff.setAlternatingRowColors(True)
        lay_diff.addWidget(self.table_diff)
        layout.addWidget(groupe_diff, stretch=1)

        self.lbl_etat = QLabel("")
        self.lbl_etat.setStyleSheet("color: #e5c07b; font-style: italic;")
        self.lbl_etat.setWordWrap(True)
        layout.addWidget(self.lbl_etat)

        self.charger_audits()

    def charger_audits(self):
        self.audits = []
        for e in audit_charger_historique():
            if isinstance(e, dict) and e.get("date"):
                self.audits.append(e)
        try:
            self.audits.sort(key=lambda e: e.get("date", ""))
        except Exception:
            pass

        self.combo_avant.clear()
        self.combo_apres.clear()
        for i, e in enumerate(self.audits):
            texte = f"{e['date']} — Score {e.get('score', '?')}/100"
            self.combo_avant.addItem(texte, i)
            self.combo_apres.addItem(texte, i)
        if len(self.audits) >= 2:
            self.combo_avant.setCurrentIndex(0)
            self.combo_apres.setCurrentIndex(len(self.audits) - 1)
        elif len(self.audits) == 1:
            self.combo_avant.setCurrentIndex(0)
            self.combo_apres.setCurrentIndex(0)
            self.lbl_etat.setText("Un seul audit enregistré — la comparaison A/B nécessite au moins deux audits.")
        else:
            self.lbl_etat.setText("Aucun audit enregistré — lancez un premier audit dans la Zone 9.")
        self.generer_tendance()

    def generer_tendance(self):
        if not self.audits:
            self.txt_tendance.setPlainText("(aucun audit enregistré)")
            return
        blocs = "▁▂▃▄▅▆▇█"
        morceaux = []
        for e in self.audits:
            try:
                score = int(e.get("score", 0) or 0)
            except Exception:
                score = 0
            score = max(0, min(100, score))
            morceaux.append(blocs[score * (len(blocs) - 1) // 100])
        dates = [e.get("date", "?") for e in self.audits]
        scores = []
        for e in self.audits:
            try:
                scores.append(int(e.get("score", 0) or 0))
            except Exception:
                pass
        lignes = [
            "Evolution : " + " ".join(morceaux),
            f"Période   : {dates[0]} → {dates[-1]}",
            f"Scores    : minimum {min(scores)} — maximum {max(scores)} — actuel {scores[-1]}",
        ]
        self.txt_tendance.setPlainText("\n".join(lignes))

    def comparer(self):
        idx_a = self.combo_avant.currentData()
        idx_b = self.combo_apres.currentData()
        if idx_a is None or idx_b is None or not self.audits:
            QMessageBox.information(
                self, "Comparaison impossible",
                "Aucun audit à comparer.\nLancez d'abord des audits dans la Zone 9."
            )
            return
        avant = self.audits[idx_a]
        apres = self.audits[idx_b]

        try:
            score_a = int(avant.get("score", 0) or 0)
        except Exception:
            score_a = 0
        try:
            score_b = int(apres.get("score", 0) or 0)
        except Exception:
            score_b = 0
        delta = score_b - score_a

        couleur_a = couleur_score_audit(score_a)
        couleur_b = couleur_score_audit(score_b)
        self.lbl_titre_a.setText(f"Audit A — {avant.get('date', '?')}")
        self.lbl_titre_b.setText(f"Audit B — {apres.get('date', '?')}")
        self.lbl_score_a.setText(str(score_a))
        self.lbl_score_a.setStyleSheet(f"font-size: 34px; font-weight: bold; color: {couleur_a};")
        self.lbl_score_b.setText(str(score_b))
        self.lbl_score_b.setStyleSheet(f"font-size: 34px; font-weight: bold; color: {couleur_b};")
        self.barre_a.setValue(score_a)
        self.barre_a.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {couleur_a}; border-radius: 5px; }}"
        )
        self.barre_b.setValue(score_b)
        self.barre_b.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {couleur_b}; border-radius: 5px; }}"
        )
        if delta > 0:
            self.lbl_delta.setText(f"▲\n▲ +{delta} pts")
            self.lbl_delta.setStyleSheet("font-weight: bold; color: #98c379; font-size: 13px;")
        elif delta < 0:
            self.lbl_delta.setText(f"▼\n▼ {delta} pts")
            self.lbl_delta.setStyleSheet("font-weight: bold; color: #e06c75; font-size: 13px;")
        else:
            self.lbl_delta.setText("=\n= 0 pt")
            self.lbl_delta.setStyleSheet("font-weight: bold; color: #606b7d; font-size: 13px;")

        rapport_avant = audit_charger_rapport(avant.get("fichier"))
        rapport_apres = audit_charger_rapport(apres.get("fichier"))

        def cle(rec):
            return (rec.get("category", ""), rec.get("title", ""))

        lignes_diff = []
        detail_disponible = rapport_avant is not None and rapport_apres is not None
        if detail_disponible:
            recs_avant = {cle(r): r for r in rapport_avant.get("recommendations", [])}
            recs_apres = {cle(r): r for r in rapport_apres.get("recommendations", [])}
            for k in recs_apres:
                if k not in recs_avant:
                    lignes_diff.append({"statut": "apparue", "rec": recs_apres[k]})
            for k in recs_avant:
                if k not in recs_apres:
                    lignes_diff.append({"statut": "resolue", "rec": recs_avant[k]})
                else:
                    lignes_diff.append({"statut": "persistante", "rec": recs_apres[k]})
            ordre = {"resolue": 0, "apparue": 1, "persistante": 2}
            lignes_diff.sort(key=lambda d: (ordre[d["statut"]], d["rec"]["category"], d["rec"]["title"]))
            self.lbl_etat.setText("")
        else:
            self.lbl_etat.setText(
                "Diff détaillé indisponible : au moins un des deux audits date d'une version antérieure\n"
                "à l'archivage complet. Seuls le score et la tendance sont comparés.\n"
                "Relancez un audit (Zone 9) avec cette version pour obtenir le diff complet."
            )

        self.table_diff.setRowCount(0)
        for item in lignes_diff:
            libelle = self.STATUTS[item["statut"]][0]
            rec = item["rec"]
            ligne = self.table_diff.rowCount()
            self.table_diff.insertRow(ligne)
            self.table_diff.setItem(ligne, 0, QTableWidgetItem(libelle))
            self.table_diff.setItem(ligne, 1, QTableWidgetItem(rec.get("level", "")))
            self.table_diff.setItem(ligne, 2, QTableWidgetItem(rec.get("title", "")))
            self.table_diff.setItem(ligne, 3, QTableWidgetItem(rec.get("action", "")))
        self.table_diff.resizeRowsToContents()

        self.resultat_compare = {
            "avant": avant,
            "apres": apres,
            "delta": delta,
            "detail_disponible": detail_disponible,
            "lignes_diff": lignes_diff,
        }
        self.btn_export_html.setEnabled(True)

    def exporter_comparaison(self):
        if not self.resultat_compare:
            return
        try:
            d = self.resultat_compare
            avant = d["avant"]
            apres = d["apres"]
            score_a = avant.get("score", 0)
            score_b = apres.get("score", 0)
            delta = d["delta"]
            couleur_delta = ("#98c379" if delta > 0 else "#e06c75" if delta < 0 else "#606b7d")

            def table_statut(statut, motif, couleur):
                items = [x for x in d["lignes_diff"] if x["statut"] == statut]
                if not items:
                    return (f'<tr><td colspan="4" style="color:#606b7d;text-align:center;">'
                            f"Aucune recommandation pour ce statut</td></tr>")
                html = ""
                for x in items:
                    rec = x["rec"]
                    html += f"""
                <tr>
                  <td style="color:{couleur};white-space:nowrap;"><b>{motif}</b></td>
                  <td>{rec['category']}</td>
                  <td><b>{rec['title']}</b><br/>{rec['description']}</td>
                  <td>{rec['action']}</td>
                </tr>"""
                return html

            motif_resolue, couleur_resolue = "🟢 RÉSOLUE", "#98c379"
            motif_apparue, couleur_apparue = "🔴 APPARUE", "#e06c75"
            motif_persistante, couleur_persistante = "🟡 PERSISTANTE", "#e5c07b"
            html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8"/>
<title>Comparaison d'audits KareDiag</title>
<style>
  body {{ background-color:#181a1f; color:#abb2bf; font-family:sans-serif; margin:2em; }}
  h1, h2 {{ color:#00bcd4; }}
  .delta {{ font-size:2.2em; font-weight:bold; color:{couleur_delta}; }}
  table {{ border-collapse:collapse; width:100%; margin-top:1em; }}
  th, td {{ border:1px solid #3e4451; padding:6px 10px; text-align:left; vertical-align:top; }}
  th {{ background-color:#21252b; color:#00bcd4; }}
  .meta {{ color:#606b7d; font-size:0.9em; }}
</style>
</head>
<body>
<h1>Comparaison d'audits KareDiag</h1>
<p class="meta">Éditée le {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
<p>
  Audit A : {avant.get('date', '?')} — score <b>{score_a}/100</b><br/>
  Audit B : {apres.get('date', '?')} — score <b>{score_b}/100</b><br/>
  Évolution : <span class="delta">{'+' if delta > 0 else ''}{delta} points</span>
</p>
<h2>Recommandations</h2>
<table>
  <tr><th>Statut</th><th>Catégorie</th><th>Constat</th><th>Action</th></tr>
{table_statut('resolue', motif_resolue, couleur_resolue)}
{table_statut('apparue', motif_apparue, couleur_apparue)}
{table_statut('persistante', motif_persistante, couleur_persistante)}
</table>
</body>
</html>"""
            chemin = os.path.join(
                bureau_utilisateur(),
                f"karediag_comparaison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            )
            with open(chemin, "w", encoding="utf-8") as f:
                f.write(html)
            QMessageBox.information(
                self, "Comparaison exportée",
                f"Le rapport HTML a été enregistré ici :\n{chemin}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Erreur lors de l'export de la comparaison :\n{e}")


class KOutilsDisquesWindow(QDialog):
    """Zone 5 avancée : fsck, test de surface, TRIM et attributs NVMe.

    Vérification = lecture seule. Réparation = partition démontée +
    confirmation explicite. Aucun mode destructeur (badblocks -w,
    btrfs check --repair) n'est exposé.
    """

    FS_OUTILS = {
        "ext2": ("e2fsck", ["-fn"], ["-fy"]),
        "ext3": ("e2fsck", ["-fn"], ["-fy"]),
        "ext4": ("e2fsck", ["-fn"], ["-fy"]),
        "xfs": ("xfs_repair", ["-n"], []),
        "vfat": ("fsck.vfat", ["-n"], ["-a"]),
        "fat32": ("fsck.vfat", ["-n"], ["-a"]),
        "msdos": ("fsck.vfat", ["-n"], ["-a"]),
        "ntfs": ("ntfsfix", ["-n"], ["-d"]),
    }

    def __init__(self, parent=None, disque_courant=None):
        super().__init__(parent)
        self.setWindowTitle("KareDiag - Outils disques avancés (Zone 5)")
        self.resize(860, 760)
        self.setMinimumSize(780, 660)
        self.process = None
        self.disque_courant = disque_courant
        self.fin_callback = None
        self.sortie = ""
        self.t0 = datetime.now()
        self.duree_op = 0

        self.setStyleSheet("""
            QDialog { background-color: #181a1f; }
            QGroupBox {
                color: #00bcd4; font-weight: bold; font-size: 13px;
                border: 2px solid #3e4451; border-radius: 8px;
                margin-top: 12px; background-color: rgba(33, 37, 43, 210);
            }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
            QPushButton {
                background-color: #2188ff; color: white; border-radius: 4px;
                padding: 6px 12px; font-weight: bold; border: none;
            }
            QPushButton:hover { background-color: #006fe6; }
            QPushButton:disabled { background-color: #3b4252; color: #606b7d; }
            QLabel { color: #abb2bf; font-size: 12px; }
            QComboBox {
                background-color: #21252b; border: 1px solid #4b5263;
                border-radius: 4px; padding: 4px; color: #abb2bf;
            }
            QTextEdit {
                background-color: #1e1e1e; color: #00ff00;
                font-family: monospace; font-size: 10px;
                border: 1px solid #3e4451; border-radius: 4px;
            }
        """)

        layout = QVBoxLayout(self)

        titre = QLabel("Zone 5 avancée - Outils disques (fsck / surface / SSD-NVMe)")
        titre.setStyleSheet("font-size: 14px; font-weight: bold; color: #00bcd4;")
        titre.setAlignment(Qt.AlignCenter)
        layout.addWidget(titre)

        note = QLabel(
            "Vérification et réparation des systèmes de fichiers, test de surface, TRIM, attributs NVMe.\n"
            "Vérification = lecture seule. Réparation = partition démontée + confirmation obligatoire."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        groupe_cible = QGroupBox(" Cible ")
        row_cible = QHBoxLayout()
        row_cible.addWidget(QLabel("Disque / partition :"))
        self.combo_cible = QComboBox()
        self.combo_cible.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_rafraichir = QPushButton("Rafraîchir")
        self.btn_rafraichir.clicked.connect(self.charger_cibles)
        row_cible.addWidget(self.combo_cible, stretch=1)
        row_cible.addWidget(self.btn_rafraichir)
        groupe_cible.setLayout(row_cible)
        layout.addWidget(groupe_cible)

        self.lbl_etat_cible = QLabel("Analyse en cours...")
        self.lbl_etat_cible.setWordWrap(True)
        layout.addWidget(self.lbl_etat_cible)

        groupe_fs = QGroupBox(" Systèmes de fichiers ")
        lay_fs = QVBoxLayout(groupe_fs)
        row_fs = QHBoxLayout()
        self.btn_demonter = QPushButton("Démonter la cible")
        self.btn_demonter.clicked.connect(self.demonter_cible)
        self.btn_verifier_fs = QPushButton("Vérifier (lecture seule)")
        self.btn_verifier_fs.clicked.connect(self.verifier_fs)
        self.btn_reparer_fs = QPushButton("Réparer (confirmation)")
        self.btn_reparer_fs.clicked.connect(self.reparer_fs)
        row_fs.addWidget(self.btn_demonter)
        row_fs.addWidget(self.btn_verifier_fs)
        row_fs.addWidget(self.btn_reparer_fs)
        lay_fs.addLayout(row_fs)
        self.lbl_fs_info = QLabel(
            "ext2/3/4 : e2fsck — xfs : xfs_repair — vfat : fsck.vfat — ntfs : ntfsfix — btrfs : scrub (monté)."
        )
        self.lbl_fs_info.setStyleSheet("color: #606b7d; font-style: italic;")
        self.lbl_fs_info.setWordWrap(True)
        lay_fs.addWidget(self.lbl_fs_info)
        layout.addWidget(groupe_fs)

        groupe_surface = QGroupBox(" Test de surface ")
        lay_surface = QVBoxLayout(groupe_surface)
        row_surface = QHBoxLayout()
        self.btn_debit = QPushButton("⏱️ Débit lecture (~10 s)")
        self.btn_debit.clicked.connect(self.lancer_debit)
        self.btn_badblocks = QPushButton("🧱 badblocks complet (heures)")
        self.btn_badblocks.clicked.connect(self.lancer_badblocks)
        row_surface.addWidget(self.btn_debit)
        row_surface.addWidget(self.btn_badblocks)
        lay_surface.addLayout(row_surface)
        lbl_surface = QLabel(
            "Les deux tests sont en LECTURE SEULE : aucune écriture sur vos données.\n"
            "Le débit moyen anormal (comparé aux autres disques) révèle des secteurs lents."
        )
        lbl_surface.setStyleSheet("color: #606b7d; font-style: italic;")
        lbl_surface.setWordWrap(True)
        lay_surface.addWidget(lbl_surface)
        layout.addWidget(groupe_surface)

        groupe_ssd = QGroupBox(" SSD / NVMe ")
        lay_ssd = QVBoxLayout(groupe_ssd)
        row_ssd = QHBoxLayout()
        self.btn_trim = QPushButton("✨ fstrim (partitions montées)")
        self.btn_trim.clicked.connect(self.lancer_trim)
        self.btn_nvme = QPushButton("🧠 Attributs NVMe (usure, température)")
        self.btn_nvme.clicked.connect(self.lancer_nvme)
        row_ssd.addWidget(self.btn_trim)
        row_ssd.addWidget(self.btn_nvme)
        lay_ssd.addLayout(row_ssd)
        self.lbl_trim_timer = QLabel("TRIM périodique : vérification...")
        self.lbl_trim_timer.setWordWrap(True)
        lay_ssd.addWidget(self.lbl_trim_timer)
        layout.addWidget(groupe_ssd)

        row_btns = QHBoxLayout()
        self.btn_arreter = QPushButton("Arrêter l'opération en cours")
        self.btn_arreter.setEnabled(False)
        self.btn_arreter.clicked.connect(self.arreter)
        row_btns.addWidget(self.btn_arreter)
        layout.addLayout(row_btns)

        groupe_log = QGroupBox(" Journal des opérations ")
        log_layout = QVBoxLayout(groupe_log)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            background-color: #1e1e1e;
            color: #00ff00;
            font-family: monospace;
            font-size: 10px;
            border: 1px solid #3e4451;
            border-radius: 4px;
        """)
        log_layout.addWidget(self.log_text)
        layout.addWidget(groupe_log, stretch=1)

        self.charger_cibles()
        self.maj_trim_timer()

    def log(self, message):
        self.log_text.append(message)

    def charger_cibles(self):
        avant = self.combo_cible.currentData() or self.disque_courant
        self.combo_cible.clear()
        for b in lister_blocs():
            self.combo_cible.addItem(b["affichage"], b["nom"])
        if avant:
            idx = self.combo_cible.findData(avant)
            if idx >= 0:
                self.combo_cible.setCurrentIndex(idx)
        self.maj_etat_cible()

    def cible_courante(self):
        return self.combo_cible.currentData()

    def exiger_cible(self):
        cible = self.cible_courante()
        if not cible:
            QMessageBox.warning(
                self, "Cible invalide", "Sélectionnez un disque ou une partition."
            )
        return cible

    def fstype_cible(self, cible):
        try:
            res = subprocess.run(
                ["lsblk", "-rno", "FSTYPE", cible], capture_output=True, text=True
            )
            for ligne in res.stdout.splitlines():
                ligne = ligne.strip()
                if ligne:
                    return ligne
        except Exception:
            pass
        return None

    def point_montage(self, cible):
        try:
            res = subprocess.run(
                ["lsblk", "-rno", "MOUNTPOINT", cible], capture_output=True, text=True
            )
            for ligne in res.stdout.splitlines():
                ligne = ligne.strip()
                if ligne:
                    return ligne
        except Exception:
            pass
        return None

    def maj_etat_cible(self):
        cible = self.cible_courante()
        if not cible:
            self.lbl_etat_cible.setText("Aucune cible détectée — cliquez sur Rafraîchir.")
            self.lbl_etat_cible.setStyleSheet("font-weight: bold; color: #e5c07b;")
            return
        fstype = self.fstype_cible(cible)
        mp = self.point_montage(cible)
        morceaux = [cible, "système de fichiers : " + (fstype or "inconnu")]
        if mp:
            morceaux.append("montée sur " + mp + (" (SYSTÈME ACTIF)" if mp == "/" else ""))
        else:
            morceaux.append("démontée ✅")
        self.lbl_etat_cible.setText("Cible : " + " — ".join(morceaux))
        if mp == "/":
            self.lbl_etat_cible.setStyleSheet("font-weight: bold; color: #e06c75;")
        elif mp:
            self.lbl_etat_cible.setStyleSheet("font-weight: bold; color: #e5c07b;")
        else:
            self.lbl_etat_cible.setStyleSheet("font-weight: bold; color: #98c379;")

    def maj_trim_timer(self):
        try:
            actif = subprocess.run(
                ["systemctl", "is-enabled", "fstrim.timer"],
                capture_output=True, text=True
            ).returncode == 0
        except Exception:
            actif = False
        if actif:
            self.lbl_trim_timer.setText("TRIM périodique (fstrim.timer) : ✅ activé")
        else:
            self.lbl_trim_timer.setText(
                "TRIM périodique (fstrim.timer) : ❌ désactivé\n"
                "sudo systemctl enable --now fstrim.timer"
            )

    def demonter_cible(self):
        cible = self.cible_courante()
        if not cible:
            return False
        fstype = self.fstype_cible(cible)
        if fstype == "swap":
            r = subprocess.run(
                prefixe_privilege() + ["swapoff", cible], capture_output=True, text=True
            )
            if r.returncode == 0:
                self.log("Swap désactivé sur " + cible)
            else:
                self.log("swapoff a échoué : " + (r.stderr.strip() or "erreur inconnue"))
        else:
            erreurs = demonter_chemin(cible, log_fn=self.log)
            if erreurs:
                QMessageBox.critical(
                    self, "Démontage impossible",
                    "Impossible de démonter la cible :\n" + "\n".join(erreurs)
                )
                return False
        if self.point_montage(cible):
            self.maj_etat_cible()
            QMessageBox.critical(
                self, "Démontage impossible", "La cible est encore montée."
            )
            return False
        self.maj_etat_cible()
        return True

    def verifier_fs(self):
        cible = self.exiger_cible()
        if not cible:
            return
        mp = self.point_montage(cible)
        if mp == "/":
            QMessageBox.critical(
                self, "Opération interdite",
                "La cible contient le système actif.\n"
                "Un fsck sur une racine montée est refusé."
            )
            return
        fstype = self.fstype_cible(cible)
        if fstype == "btrfs":
            if not mp:
                QMessageBox.warning(
                    self, "btrfs non montée",
                    "La vérification btrfs (scrub) s'exécute sur un système MONTÉ.\n"
                    "Montez la partition puis relancez la vérification."
                )
                return
            args = prefixe_privilege() + ["btrfs", "scrub", "start", "-B", mp]
        elif fstype in self.FS_OUTILS:
            outil, args_verif, _ = self.FS_OUTILS[fstype]
            if not shutil.which(outil):
                QMessageBox.critical(
                    self, "Outil manquant",
                    f"{outil} est introuvable sur ce système.\n"
                    "Installez le paquet requis :\n\n"
                    "sudo apt install e2fsprogs  (ou xfsprogs, dosfstools, ntfs-3g)"
                )
                return
            if mp:
                reponse = QMessageBox.question(
                    self, "Partition montée",
                    f"{cible} est montée sur {mp}.\n"
                    "La vérification doit se faire à froid.\n\n"
                    "La démonter maintenant ?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if reponse != QMessageBox.Yes or not self.demonter_cible():
                    return
            args = prefixe_privilege() + [outil] + args_verif + [cible]
        else:
            QMessageBox.warning(
                self, "Type non géré",
                f"Type « {fstype or 'inconnu'} » non géré par l'assistant fsck."
            )
            return
        self.lancer_process(args, "Vérification fs (lecture seule)")

    def reparer_fs(self):
        cible = self.exiger_cible()
        if not cible:
            return
        fstype = self.fstype_cible(cible)
        if fstype == "btrfs":
            QMessageBox.warning(
                self, "Réparation btrfs",
                "La réparation manuelle btrfs (check --repair) est jugée trop\n"
                "dangereuse pour être proposée ici : utilisez scrub (monté),\n"
                "ou effectuez d'abord une image de secours via la Zone 4."
            )
            return
        if fstype not in self.FS_OUTILS:
            QMessageBox.warning(
                self, "Type non géré",
                f"Type « {fstype or 'inconnu'} » non géré : pas de réparation automatique."
            )
            return
        outil, _, args_rep = self.FS_OUTILS[fstype]
        if not shutil.which(outil):
            QMessageBox.critical(
                self, "Outil manquant",
                f"{outil} est introuvable sur ce système."
            )
            return
        mp = self.point_montage(cible)
        if mp:
            QMessageBox.critical(
                self, "Partition montée",
                f"{cible} est montée sur {mp}.\n"
                "Démontez-la d'abord (bouton « Démonter la cible »)."
            )
            return
        reponse = QMessageBox.question(
            self, "Réparation du système de fichiers",
            f"Réparer {cible} ({fstype}) avec : {outil} {' '.join(args_rep)} {cible}\n\n"
            "Une réparation MODIFIE le système de fichiers. Si les données sont\n"
            "importantes, sauvegardez-les avant (Zone 4 : clonage / image).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reponse != QMessageBox.Yes:
            return
        self.lancer_process(
            prefixe_privilege() + [outil] + args_rep + [cible], "Réparation fs"
        )

    def lancer_debit(self):
        cible = self.exiger_cible()
        if not cible:
            return
        args = prefixe_privilege() + [
            "dd", f"if={cible}", "of=/dev/null", "bs=1M", "count=1024"
        ]
        self.lancer_process(args, "Test de débit (1 Go en lecture)", self.fin_debit)

    def fin_debit(self, code):
        if code == 0 and self.duree_op > 0:
            self.log(f"Débit moyen : {1024 / self.duree_op:.0f} Mo/s")

    def lancer_badblocks(self):
        cible = self.exiger_cible()
        if not cible:
            return
        if not shutil.which("badblocks"):
            QMessageBox.critical(
                self, "Outil manquant",
                "badblocks est introuvable sur ce système.\n\n"
                "sudo apt install e2fsprogs"
            )
            return
        reponse = QMessageBox.question(
            self, "Test de surface complet",
            "badblocks va LIRE l'intégralité de la surface.\n\n"
            "Très long (plusieurs heures sur un disque de grande capacité)\n"
            "mais inoffensif : LECTURE SEULE, aucune écriture.\n\n"
            f"Lancer le test sur {cible} ?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reponse == QMessageBox.Yes:
            args = prefixe_privilege() + ["badblocks", "-sv", "-b", "4096", cible]
            self.lancer_process(args, "Test de surface (badblocks)")

    def lancer_trim(self):
        self.lancer_process(prefixe_privilege() + ["fstrim", "-av"], "TRIM (fstrim -a)")

    def lancer_nvme(self):
        cible = self.exiger_cible()
        if not cible or "nvme" not in os.path.basename(cible):
            QMessageBox.warning(
                self, "Cible non NVMe",
                "Sélectionnez un disque NVMe (ou une de ses partitions)."
            )
            return
        dev = disque_parent(cible) or cible
        if shutil.which("nvme"):
            self.lancer_process(
                prefixe_privilege() + ["nvme", "smart-log", dev],
                "Attributs NVMe", self.fin_nvme
            )
        elif shutil.which("smartctl"):
            self.lancer_process(
                prefixe_privilege() + ["smartctl", "-a", dev],
                "SMART NVMe (smartctl)", self.fin_nvme
            )
        else:
            QMessageBox.critical(
                self, "Outil manquant",
                "Ni nvme-cli ni smartmontools ne sont installés.\n\n"
                "sudo apt install nvme-cli"
            )

    def fin_nvme(self, code):
        if code != 0:
            return
        texte = self.sortie

        def cherche(motif):
            m = re.search(motif, texte, re.IGNORECASE)
            return m.group(1).strip() if m else None

        morceaux = []
        usure = cherche(r"percentage[_ ]used\s*:\s*(\d+)")
        if usure is not None:
            morceaux.append(f"usure : {usure} %")
        temp = cherche(r"temperature\s*:?\s*(-?\d+)")
        if temp is not None:
            morceaux.append(f"{temp} °C")
        duw = cherche(r"data[_ ]units[_ ]written\s*:\s*([\d, .]+)")
        if duw:
            chiffres = re.sub(r"[^\d]", "", duw)
            if chiffres:
                morceaux.append(f"{int(chiffres) * 512000 / 1e12:.2f} To écrits")
        erreurs = cherche(r"media[_ ]errors\s*:\s*([\d,]+)")
        if erreurs is not None:
            morceaux.append("erreurs médias : " + erreurs.replace(",", ""))
        if morceaux:
            self.log("Synthèse NVMe : " + " · ".join(morceaux))

    def set_boutons_actifs(self, actif):
        for b in (self.btn_demonter, self.btn_verifier_fs, self.btn_reparer_fs,
                  self.btn_debit, self.btn_badblocks, self.btn_trim, self.btn_nvme,
                  self.btn_rafraichir):
            b.setEnabled(actif)
        self.btn_arreter.setEnabled(not actif)

    def lancer_process(self, args, titre, fin=None):
        if self.process is not None:
            QMessageBox.warning(
                self, "Opération en cours",
                "Un outil est déjà en cours d'exécution."
            )
            return
        self.op_titre = titre
        self.fin_callback = fin
        self.t0 = datetime.now()
        self.duree_op = 0
        self.sortie = ""
        self.log("---")
        self.log("Commande : " + " ".join(args))
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.lire_sortie)
        self.process.finished.connect(lambda code, statut: self.operation_terminee(titre, code))
        self.process.errorOccurred.connect(self.erreur_processus)
        self.process.start(args[0], args[1:])
        self.set_boutons_actifs(False)

    def lire_sortie(self):
        if self.process is None:
            return
        donnees = bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace")
        self.sortie += donnees
        for ligne in donnees.replace("\r", "\n").splitlines():
            ligne = ligne.strip()
            if ligne:
                self.log(ligne)

    ERREURS_PROCESSUS = {
        0: "impossible de démarrer (commande introuvable ?)",
        1: "interrompu (arrêt demandé ou plantage)",
        2: "délai dépassé",
        3: "erreur d'écriture",
        4: "erreur de lecture",
        5: "erreur inconnue",
    }

    def decrire_code_retour(self, code):
        if code in (9, 137, -9):
            return "interrompu par l'utilisateur (bouton « Arrêter »)"
        if code in (15, 143, -15):
            return "interrompu (SIGTERM)"
        if code == 1:
            return "échec — voir les messages ci-dessus dans le journal"
        return None

    def operation_terminee(self, titre, code):
        try:
            duree = (datetime.now() - self.t0).total_seconds()
        except Exception:
            duree = 0
        self.duree_op = duree
        rappel = self.fin_callback
        self.fin_callback = None
        cause = self.decrire_code_retour(code)
        suffixe = f" ({cause})" if cause else ""
        self.log(f"[{titre}] terminé — code retour {code}{suffixe} — {duree:.0f} s")
        if self.process is not None:
            self.process.deleteLater()
            self.process = None
        self.set_boutons_actifs(True)
        if rappel:
            try:
                rappel(code)
            except Exception as e:
                self.log(f"Erreur d'analyse du résultat : {e}")

    def erreur_processus(self, erreur):
        if self.process is None:
            return
        motif = self.ERREURS_PROCESSUS.get(erreur, f"code {erreur}")
        self.log(f"Erreur du processus : {motif}")
        self.fin_callback = None
        self.process.deleteLater()
        self.process = None
        self.set_boutons_actifs(True)

    def arreter(self):
        if self.process is not None:
            self.log("Interruption demandée par l'utilisateur...")
            self.process.kill()


class KRecuperationWindow(QDialog):
    """Zone 3 : récupération de données (PhotoRec non-interactif, TestDisk)."""

    def __init__(self, parent=None, disque_courant=None):
        super().__init__(parent)
        self.setWindowTitle("KareDiag - Récupération de données (Zone 3)")
        self.resize(800, 640)
        self.setMinimumSize(700, 560)
        self.process = None
        self.disque_courant = disque_courant

        self.setStyleSheet("""
            QDialog { background-color: #181a1f; }
            QGroupBox {
                color: #00bcd4; font-weight: bold; font-size: 13px;
                border: 2px solid #3e4451; border-radius: 8px;
                margin-top: 12px; background-color: rgba(33, 37, 43, 210);
            }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
            QPushButton {
                background-color: #2188ff; color: white; border-radius: 4px;
                padding: 6px 12px; font-weight: bold; border: none;
            }
            QPushButton:hover { background-color: #006fe6; }
            QPushButton:disabled { background-color: #3b4252; color: #606b7d; }
            QLabel { color: #abb2bf; font-size: 12px; }
            QComboBox, QLineEdit {
                background-color: #21252b; border: 1px solid #4b5263;
                border-radius: 4px; padding: 4px; color: #abb2bf;
            }
        """)

        layout = QVBoxLayout(self)

        titre = QLabel("Zone 3 - Récupération de données")
        titre.setStyleSheet("font-size: 14px; font-weight: bold; color: #00bcd4;")
        titre.setAlignment(Qt.AlignCenter)
        layout.addWidget(titre)

        note = QLabel(
            "PhotoRec récupère les fichiers effacés ; TestDisk (interactif, dans un terminal) répare les partitions perdues.\n"
            "La destination doit TOUJOURS être sur un autre disque que la cible.\n"
            "Disque défaillant ? Clonez-le d'abord (Zone 4), puis scannez l'image .img."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        groupe_cible = QGroupBox(" Cible à analyser ")
        row_cible = QHBoxLayout()
        row_cible.addWidget(QLabel("Disque / partition :"))
        self.combo_cible = QComboBox()
        self.combo_cible.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row_cible.addWidget(self.combo_cible, stretch=1)
        self.btn_rafraichir = QPushButton("Rafraîchir")
        self.btn_rafraichir.clicked.connect(self.charger_cibles)
        row_cible.addWidget(self.btn_rafraichir)
        groupe_cible.setLayout(row_cible)
        layout.addWidget(groupe_cible)

        groupe_dest = QGroupBox(" Dossier de destination (sur un AUTRE disque) ")
        row_dest = QHBoxLayout()
        self.txt_dest = QLineEdit()
        self.btn_dest = QPushButton("Choisir...")
        self.btn_dest.clicked.connect(self.choisir_destination)
        row_dest.addWidget(self.txt_dest, stretch=1)
        row_dest.addWidget(self.btn_dest)
        groupe_dest.setLayout(row_dest)
        layout.addWidget(groupe_dest)

        self.lbl_outils = QLabel("Outils : vérification en cours...")
        self.lbl_outils.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.lbl_outils)

        row_btns = QHBoxLayout()
        self.btn_photorec = QPushButton("🔎 Lancer PhotoRec")
        self.btn_photorec.clicked.connect(self.lancer_photorec)
        self.btn_testdisk = QPushButton("🖥️ Ouvrir TestDisk (terminal)")
        self.btn_testdisk.clicked.connect(self.ouvrir_testdisk)
        self.btn_arreter = QPushButton("Arrêter")
        self.btn_arreter.setEnabled(False)
        self.btn_arreter.clicked.connect(self.arreter)
        row_btns.addWidget(self.btn_photorec)
        row_btns.addWidget(self.btn_testdisk)
        row_btns.addWidget(self.btn_arreter)
        layout.addLayout(row_btns)

        groupe_log = QGroupBox(" Journal des opérations ")
        log_layout = QVBoxLayout(groupe_log)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            background-color: #1e1e1e;
            color: #00ff00;
            font-family: monospace;
            font-size: 10px;
            border: 1px solid #3e4451;
            border-radius: 4px;
        """)
        log_layout.addWidget(self.log_text)
        layout.addWidget(groupe_log)

        self.txt_dest.setText(bureau_utilisateur())
        self.charger_cibles()
        self.verifier_outils()

    def logg(self, message):
        self.log_text.append(message)

    def charger_cibles(self):
        avant = self.combo_cible.currentData()
        self.combo_cible.clear()
        for b in lister_blocs():
            self.combo_cible.addItem(b["affichage"], b["nom"])
        for cible in (avant, self.disque_courant):
            if cible:
                idx = self.combo_cible.findData(cible)
                if idx >= 0:
                    self.combo_cible.setCurrentIndex(idx)
                    break

    def choisir_destination(self):
        dossier = QFileDialog.getExistingDirectory(
            self, "Dossier de récupération",
            self.txt_dest.text().strip() or os.path.expanduser("~")
        )
        if dossier:
            self.txt_dest.setText(dossier)

    def verifier_outils(self):
        photorec = shutil.which("photorec")
        testdisk = shutil.which("testdisk")
        ddrescue = shutil.which("ddrescue")
        self.lbl_outils.setText(
            "Outils : PhotoRec " + ("✅" if photorec else "❌")
            + " | TestDisk " + ("✅" if testdisk else "❌")
            + " | ddrescue " + ("✅" if ddrescue else "❌")
        )
        if photorec and testdisk:
            self.lbl_outils.setStyleSheet("font-weight: bold; color: #98c379;")
        else:
            self.lbl_outils.setStyleSheet("font-weight: bold; color: #e5c07b;")
            self.logg("Outils manquants — installation : sudo apt install testdisk gddrescue")
        return bool(photorec)

    def verifier_destination(self, cible):
        chemin = self.txt_dest.text().strip()
        if not chemin or not os.path.isdir(chemin):
            QMessageBox.critical(
                self, "Destination invalide",
                "Choisissez un dossier de destination existant."
            )
            return False
        try:
            res = subprocess.run(["df", "-P", chemin], capture_output=True, text=True)
            lignes = res.stdout.strip().splitlines()
            if len(lignes) >= 2:
                device_dest = lignes[1].split()[0]
                disque_dest = disque_parent(device_dest) or device_dest
                disque_cible = disque_parent(cible) or cible
                if disque_dest == disque_cible:
                    QMessageBox.critical(
                        self, "Opération interdite",
                        "La destination se trouve sur le même disque que la cible.\n"
                        "Récupérer vers le même disque risque d'écraser les données\n"
                        "à récupérer. Choisissez un dossier sur un autre disque."
                    )
                    return False
        except Exception as e:
            QMessageBox.critical(self, "Vérification impossible", str(e))
            return False
        return True

    def lancer_photorec(self):
        if self.process is not None:
            QMessageBox.warning(self, "Opération en cours", "Une analyse est déjà en cours.")
            return
        cible = self.combo_cible.currentData()
        if not cible:
            QMessageBox.warning(self, "Cible invalide", "Sélectionnez un disque ou une partition à analyser.")
            return
        if not shutil.which("photorec"):
            QMessageBox.critical(
                self, "Outil manquant",
                "photorec est introuvable sur ce système.\n"
                "Installez le paquet requis :\n\nsudo apt install testdisk"
            )
            return
        if not self.verifier_destination(cible):
            return
        prefixe_recup = os.path.join(self.txt_dest.text().strip(), "recup")
        args = prefixe_privilege() + [
            "photorec", "/d", prefixe_recup, "/cmd", cible, "fileopt,everything,enable,search"
        ]
        self.logg("---")
        self.logg("Commande : " + " ".join(args))
        QApplication.processEvents()
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.lire_sortie)
        self.process.finished.connect(lambda code, statut: self.operation_terminee("PhotoRec", code, statut))
        self.process.errorOccurred.connect(self.erreur_processus)
        self.process.start(args[0], args[1:])
        self.btn_photorec.setEnabled(False)
        self.btn_arreter.setEnabled(True)
        self.logg(
            f"PhotoRec lancé sur {cible}.\n"
            f"Les fichiers seront récupérés sous : {self.txt_dest.text().strip()}/recup.X\n"
            "(appuyez sur Arrêter pour interrompre à tout moment)"
        )

    def ouvrir_testdisk(self):
        cible = self.combo_cible.currentData()
        if not cible:
            QMessageBox.warning(self, "Cible invalide", "Sélectionnez un disque ou une partition.")
            return
        if not shutil.which("testdisk"):
            QMessageBox.critical(
                self, "Outil manquant",
                "testdisk est introuvable sur ce système.\n"
                "Installez le paquet requis :\n\nsudo apt install testdisk"
            )
            return
        candidats = [
            ["x-terminal-emulator", "-e", "testdisk", cible],
            ["konsole", "-e", "testdisk", cible],
            ["gnome-terminal", "--", "testdisk", cible],
            ["xfce4-terminal", "-e", "testdisk", cible],
            ["qterminal", "-e", "testdisk", cible],
            ["xterm", "-e", "testdisk", cible],
        ]
        for cmd in candidats:
            if shutil.which(cmd[0]):
                try:
                    subprocess.Popen(cmd, start_new_session=True)
                    self.logg(f"TestDisk lancé dans {cmd[0]} sur {cible}.")
                    return
                except Exception:
                    continue
        QMessageBox.critical(
            self, "Terminal introuvable",
            "Aucun terminal détecté (xterm, konsole, gnome-terminal...).\n"
            f"Lancez manuellement : testdisk {cible}"
        )

    def lire_sortie(self):
        if self.process is None:
            return
        donnees = bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace")
        for ligne in donnees.replace("\r", "\n").splitlines():
            ligne = ligne.strip()
            if ligne:
                self.logg(ligne)

    def operation_terminee(self, nom, code, statut):
        self.process = None
        self.btn_photorec.setEnabled(True)
        self.btn_arreter.setEnabled(False)
        if statut == QProcess.CrashExit:
            self.logg(f"{nom} : interrompu.")
            QMessageBox.warning(self, "Interrompu", f"{nom} a été interrompu.")
            return
        if code == 0:
            self.logg(f"{nom} : terminé avec succès.")
            QMessageBox.information(
                self, "Terminé",
                f"{nom} a terminé.\nConsultez le dossier de destination :\n{self.txt_dest.text().strip()}"
            )
        else:
            self.logg(f"{nom} : terminé avec le code retour {code}.")

    def erreur_processus(self, erreur):
        self.logg(f"Erreur de processus : {erreur}")

    def arreter(self):
        if self.process is not None:
            self.logg("Arrêt demandé...")
            self.process.terminate()
            QTimer.singleShot(3000, self.forcer_arret)

    def forcer_arret(self):
        if self.process is not None and self.process.state() != QProcess.NotRunning:
            self.process.kill()

    def closeEvent(self, event):
        if self.process is not None:
            self.process.terminate()
        event.accept()


class KClonageWindow(QDialog):
    """Zone 4 : clonage de disques et de partitions via ddrescue."""

    MODES = {
        "Disque → Disque": ("disk", "disk"),
        "Disque → Image (.img)": ("disk", "fichier"),
        "Partition → Partition": ("part", "part"),
        "Image (.img) → Disque / Partition": ("fichier", "tout"),
    }

    def __init__(self, parent=None, disque_courant=None):
        super().__init__(parent)
        self.setWindowTitle("KareDiag - Clonage (Zone 4)")
        self.resize(820, 660)
        self.setMinimumSize(740, 580)
        self.process = None
        self.blocs = []
        self.disque_courant = disque_courant

        self.setStyleSheet("""
            QDialog { background-color: #181a1f; }
            QGroupBox {
                color: #00bcd4; font-weight: bold; font-size: 13px;
                border: 2px solid #3e4451; border-radius: 8px;
                margin-top: 12px; background-color: rgba(33, 37, 43, 210);
            }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
            QPushButton {
                background-color: #2188ff; color: white; border-radius: 4px;
                padding: 6px 12px; font-weight: bold; border: none;
            }
            QPushButton:hover { background-color: #006fe6; }
            QPushButton:disabled { background-color: #3b4252; color: #606b7d; }
            QLabel { color: #abb2bf; font-size: 12px; }
            QComboBox, QLineEdit {
                background-color: #21252b; border: 1px solid #4b5263;
                border-radius: 4px; padding: 4px; color: #abb2bf;
            }
        """)

        layout = QVBoxLayout(self)

        titre = QLabel("Zone 4 - Clonage de disques ou de partitions")
        titre.setStyleSheet("font-size: 14px; font-weight: bold; color: #00bcd4;")
        titre.setAlignment(Qt.AlignCenter)
        layout.addWidget(titre)

        note = QLabel(
            "Outil : ddrescue (reprise possible après interruption, journal d'erreurs conservé).\n"
            "ATTENTION : la DESTINATION est entièrement écrasée. Vérifiez le sens du clonage.\n"
            "Source et destination doivent être sur des disques différents."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        groupe_sd = QGroupBox(" Source et destination ")
        gr = QGridLayout(groupe_sd)

        self.combo_mode = QComboBox()
        self.combo_mode.addItems(list(self.MODES.keys()))
        gr.addWidget(QLabel("Mode :"), 0, 0)
        gr.addWidget(self.combo_mode, 0, 1)
        self.btn_rafraichir = QPushButton("Rafraîchir")
        self.btn_rafraichir.clicked.connect(self.charger_cibles)
        gr.addWidget(self.btn_rafraichir, 0, 2)

        gr.addWidget(QLabel("Source :"), 1, 0)
        self.stack_source = QStackedWidget()
        page_src_device = QWidget()
        lay_src = QVBoxLayout(page_src_device)
        lay_src.setContentsMargins(0, 0, 0, 0)
        self.combo_source = QComboBox()
        self.combo_source.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo_source.currentIndexChanged.connect(self.maj_resume)
        lay_src.addWidget(self.combo_source)
        page_src_fichier = QWidget()
        lay_srcf = QHBoxLayout(page_src_fichier)
        lay_srcf.setContentsMargins(0, 0, 0, 0)
        self.txt_image_src = QLineEdit()
        self.txt_image_src.setPlaceholderText("Chemin de l'image source (.img)...")
        self.txt_image_src.textChanged.connect(self.maj_resume)
        self.btn_image_src = QPushButton("Parcourir...")
        self.btn_image_src.clicked.connect(self.choisir_image_src)
        lay_srcf.addWidget(self.txt_image_src, stretch=1)
        lay_srcf.addWidget(self.btn_image_src)
        self.stack_source.addWidget(page_src_device)
        self.stack_source.addWidget(page_src_fichier)
        gr.addWidget(self.stack_source, 1, 1, 1, 2)

        gr.addWidget(QLabel("Destination :"), 2, 0)
        self.stack_dest = QStackedWidget()
        page_dst_device = QWidget()
        lay_dst = QVBoxLayout(page_dst_device)
        lay_dst.setContentsMargins(0, 0, 0, 0)
        self.combo_dest = QComboBox()
        self.combo_dest.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo_dest.currentIndexChanged.connect(self.maj_resume)
        lay_dst.addWidget(self.combo_dest)
        page_dst_fichier = QWidget()
        lay_dstf = QHBoxLayout(page_dst_fichier)
        lay_dstf.setContentsMargins(0, 0, 0, 0)
        self.txt_image_dest = QLineEdit()
        self.txt_image_dest.setPlaceholderText("Chemin de l'image à créer (.img)...")
        self.txt_image_dest.textChanged.connect(self.maj_resume)
        self.btn_image_dest = QPushButton("Parcourir...")
        self.btn_image_dest.clicked.connect(self.choisir_image_dest)
        lay_dstf.addWidget(self.txt_image_dest, stretch=1)
        lay_dstf.addWidget(self.btn_image_dest)
        self.stack_dest.addWidget(page_dst_device)
        self.stack_dest.addWidget(page_dst_fichier)
        gr.addWidget(self.stack_dest, 2, 1, 1, 2)

        layout.addWidget(groupe_sd)

        self.lbl_resume = QLabel("")
        self.lbl_resume.setStyleSheet("font-weight: bold; color: #e5c07b;")
        layout.addWidget(self.lbl_resume)

        row_btns = QHBoxLayout()
        self.btn_lancer = QPushButton("🐑 Lancer le clonage")
        self.btn_lancer.clicked.connect(self.lancer_clonage)
        self.btn_arreter = QPushButton("Arrêter")
        self.btn_arreter.setEnabled(False)
        self.btn_arreter.clicked.connect(self.arreter)
        row_btns.addWidget(self.btn_lancer)
        row_btns.addWidget(self.btn_arreter)
        layout.addLayout(row_btns)

        groupe_log = QGroupBox(" Journal du clonage ")
        log_layout = QVBoxLayout(groupe_log)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            background-color: #1e1e1e;
            color: #00ff00;
            font-family: monospace;
            font-size: 10px;
            border: 1px solid #3e4451;
            border-radius: 4px;
        """)
        log_layout.addWidget(self.log_text)
        layout.addWidget(groupe_log)

        self.combo_mode.currentTextChanged.connect(self.maj_mode)
        self.charger_cibles()
        self.maj_mode()
        self.verifier_outils()

    def logg(self, message):
        self.log_text.append(message)

    def verifier_outils(self):
        if shutil.which("ddrescue"):
            return True
        self.logg("ddrescue introuvable — installation : sudo apt install gddrescue")
        return False

    def types_autorises(self, cle):
        if cle == "disk":
            return {"disk"}
        if cle == "part":
            return {"part"}
        return {"disk", "part"}

    def remplir_combo(self, combo, types, preselection=None):
        avant = combo.currentData()
        combo.clear()
        for b in self.blocs:
            if b["type"] in types:
                combo.addItem(b["affichage"], b["nom"])
        for cible in (avant, preselection):
            if cible:
                idx = combo.findData(cible)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                    break

    def charger_cibles(self):
        type_src, type_dst = self.MODES[self.combo_mode.currentText()]
        self.blocs = lister_blocs()
        self.remplir_combo(self.combo_source, self.types_autorises(type_src), self.disque_courant)
        self.remplir_combo(self.combo_dest, self.types_autorises(type_dst))
        self.maj_resume()

    def maj_mode(self):
        type_src, type_dst = self.MODES[self.combo_mode.currentText()]
        self.stack_source.setCurrentIndex(0 if type_src != "fichier" else 1)
        self.stack_dest.setCurrentIndex(0 if type_dst != "fichier" else 1)
        self.charger_cibles()

    def chemin_source(self):
        type_src, _ = self.MODES[self.combo_mode.currentText()]
        if type_src == "fichier":
            return self.txt_image_src.text().strip() or None
        return self.combo_source.currentData()

    def chemin_destination(self):
        _, type_dst = self.MODES[self.combo_mode.currentText()]
        if type_dst == "fichier":
            return self.txt_image_dest.text().strip() or None
        return self.combo_dest.currentData()

    def choisir_image_src(self):
        chemin, _ = QFileDialog.getOpenFileName(
            self, "Image disque source", os.path.expanduser("~"),
            "Images disque (*.img *.iso *.dd *.bin);;Tous les fichiers (*)"
        )
        if chemin:
            self.txt_image_src.setText(chemin)
            self.maj_resume()

    def choisir_image_dest(self):
        chemin, _ = QFileDialog.getSaveFileName(
            self, "Image disque à créer",
            os.path.join(os.path.expanduser("~"), "karediag_clonage.img"),
            "Images disque (*.img)"
        )
        if chemin:
            self.txt_image_dest.setText(chemin)
            self.maj_resume()

    def maj_resume(self):
        src = self.chemin_source()
        dst = self.chemin_destination()
        self.lbl_resume.setText(
            f"SOURCE : {src or 'à choisir'}   ➔   DESTINATION : {dst or 'à choisir'}   (la destination sera écrasée)"
        )

    def lancer_clonage(self):
        if self.process is not None:
            QMessageBox.warning(self, "Opération en cours", "Un clonage est déjà en cours.")
            return
        if not shutil.which("ddrescue"):
            QMessageBox.critical(
                self, "Outil manquant",
                "ddrescue est introuvable sur ce système.\n"
                "Installez le paquet requis :\n\nsudo apt install gddrescue"
            )
            return
        mode = self.combo_mode.currentText()
        type_src, type_dst = self.MODES[mode]
        src = self.chemin_source()
        dst = self.chemin_destination()
        if not src:
            QMessageBox.warning(self, "Source manquante", "Choisissez une source valide.")
            return
        if not dst:
            QMessageBox.warning(self, "Destination manquante", "Choisissez une destination valide.")
            return

        if type_src == "fichier" and not os.path.isfile(src):
            QMessageBox.critical(self, "Source introuvable", f"L'image {src} n'existe pas.")
            return
        if type_dst == "fichier":
            dossier = os.path.dirname(dst) or "."
            if not os.path.isdir(dossier):
                QMessageBox.critical(self, "Destination invalide", f"Le dossier {dossier} n'existe pas.")
                return

        if (src == dst
                or disque_parent(src) == dst
                or disque_parent(dst) == src
                or disque_parent(src) == disque_parent(dst)):
            QMessageBox.critical(
                self, "Collision interdite",
                "Source et destination sont sur le même disque.\n"
                "Le clonage écraserait la source — opération refusée."
            )
            return

        if type_dst != "fichier":
            tailles = {b["nom"]: b["taille"] for b in self.blocs if isinstance(b["taille"], int)}
            if type_src == "fichier":
                taille_src = os.path.getsize(src)
            else:
                taille_src = tailles.get(src)
            taille_dst = tailles.get(dst)
            if taille_src is None:
                QMessageBox.critical(
                    self, "Taille inconnue",
                    "Taille de la source inconnue. Cliquez sur Rafraîchir et réessayez."
                )
                return
            if taille_dst is None:
                QMessageBox.critical(
                    self, "Taille inconnue",
                    "Taille de la destination inconnue. Cliquez sur Rafraîchir et réessayez."
                )
                return
            if taille_src > taille_dst:
                QMessageBox.critical(
                    self, "Destination trop petite",
                    f"La destination ({taille_dst / 1024**3:.2f} Go) est plus petite que "
                    f"la source ({taille_src / 1024**3:.2f} Go).\nClonage refusé."
                )
                return

            if device_contient_systeme(dst):
                QMessageBox.critical(
                    self, "Opération interdite",
                    f"{dst} contient le système d'exploitation actif.\nClonage refusé."
                )
                return
            erreurs = demonter_destination(dst, log_fn=self.logg)
            if erreurs:
                QMessageBox.critical(
                    self, "Opération interdite",
                    "Impossible de démonter la destination :\n" + "\n".join(erreurs)
                    + "\n\nClonage annulé."
                )
                return

        confirmation = QMessageBox.question(
            self, "Confirmation critique",
            f"SOURCE : {src}\nDESTINATION : {dst}\n\n"
            "TOUTES les données de la DESTINATION seront écrasées.\n"
            "Vérifiez bien le sens du clonage.\n\nConfirmez-vous ?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if confirmation != QMessageBox.Yes:
            return

        journal = os.path.expanduser(
            f"~/karediag_ddrescue_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        )
        args = prefixe_privilege() + ["ddrescue"]
        if type_dst != "fichier":
            args.append("-f")
        args += [src, dst, journal]
        self.logg("---")
        self.logg("Commande : " + " ".join(args))
        QApplication.processEvents()
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.lire_sortie)
        self.process.finished.connect(lambda code, statut: self.clonage_termine(code, statut, journal))
        self.process.errorOccurred.connect(self.erreur_processus)
        self.process.start(args[0], args[1:])
        self.btn_lancer.setEnabled(False)
        self.btn_arreter.setEnabled(True)
        self.combo_mode.setEnabled(False)
        self.logg("Clonage en cours (progression affichée ci-dessous)...")

    def clonage_termine(self, code, statut, journal):
        self.process = None
        self.btn_lancer.setEnabled(True)
        self.btn_arreter.setEnabled(False)
        self.combo_mode.setEnabled(True)
        if statut == QProcess.CrashExit:
            self.logg("Clonage interrompu.")
            QMessageBox.warning(
                self, "Interrompu",
                "Le clonage a été interrompu.\n"
                f"Le journal ddrescue est conservé : {journal}\n"
                "ddrescue peut reprendre : relancez le même clonage."
            )
            return
        if code == 0:
            self.logg("Clonage terminé avec succès.")
            QMessageBox.information(
                self, "Succès",
                "Clonage terminé avec succès.\nJournal ddrescue :\n" + journal
            )
        else:
            self.logg(f"Clonage terminé avec le code retour {code}.")
            QMessageBox.warning(
                self, "Terminé avec anomalies",
                f"Le clonage s'est terminé avec le code {code}.\n"
                "Si la source a des secteurs défectueux, consultez le journal :\n" + journal
            )

    def lire_sortie(self):
        if self.process is None:
            return
        donnees = bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace")
        for ligne in donnees.replace("\r", "\n").splitlines():
            ligne = ligne.strip()
            if ligne:
                self.logg(ligne)

    def erreur_processus(self, erreur):
        self.logg(f"Erreur de processus : {erreur}")

    def arreter(self):
        if self.process is not None:
            self.logg("Arrêt demandé (le journal ddrescue permet la reprise)...")
            self.process.terminate()
            QTimer.singleShot(3000, self.forcer_arret)

    def forcer_arret(self):
        if self.process is not None and self.process.state() != QProcess.NotRunning:
            self.process.kill()

    def closeEvent(self, event):
        if self.process is not None:
            self.process.terminate()
        event.accept()


class KDiskApp(QMainWindow):
    def __init__(self):
        super().__init__()
        titre_fenetre = "KareDiag - Maintenance et diagnostic système (Kaisen Linux)"
        if est_root():
            titre_fenetre += "  —  [🛡️ Mode Administrateur]"
        self.setWindowTitle(titre_fenetre)
        hauteur_ecran = QApplication.primaryScreen().availableGeometry().height()
        largeur_ecran = QApplication.primaryScreen().availableGeometry().width()
        self.resize(min(1160, largeur_ecran), min(1040, int(hauteur_ecran * 0.93)))

        self.setStyleSheet("""
            QMainWindow { background-color: #181a1f; }
            QGroupBox {
                color: #00bcd4;
                font-weight: bold;
                font-size: 13px;
                border: 2px solid #3e4451;
                border-radius: 8px;
                margin-top: 12px;
                background-color: rgba(33, 37, 43, 210);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 5px;
            }
            QPushButton {
                background-color: #2188ff;
                color: white;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover { background-color: #006fe6; }
            QPushButton:disabled { background-color: #3b4252; color: #606b7d; }
            QLabel, QComboBox { color: #abb2bf; font-size: 12px; }
            QComboBox, QLineEdit {
                background-color: #21252b;
                border: 1px solid #4b5263;
                border-radius: 4px;
                padding: 4px;
                color: #abb2bf;
            }
        """)

        # Zone de défilement : toutes les zones restent accessibles,
        # même sur les écrans où la fenêtre complète est plus haute que l'écran.
        zone_defilable = QScrollArea()
        zone_defilable.setWidgetResizable(True)
        zone_defilable.setFrameShape(QFrame.NoFrame)

        central_widget = QWidget()
        central_widget.setObjectName("zone_defilement")
        # Sélecteur par identifiant : uniquement ce conteneur est recoloré,
        # sans écraser le style bleu des boutons des zones filles.
        central_widget.setStyleSheet("#zone_defilement { background-color: #181a1f; }")
        zone_defilable.setWidget(central_widget)
        self.setCentralWidget(zone_defilable)
        main_layout = QVBoxLayout(central_widget)

        self.zones_privilegiees = []

        # ==========================================
        # ZONE 1 : Connexion SU (PolicyKit)
        # ==========================================
        self.group_zone1 = QGroupBox(" Zone 1 : Connexion SU ")
        layout_zone1 = QHBoxLayout()

        self.btn_auth = QPushButton("S'authentifier (PolicyKit)")
        self.btn_auth.clicked.connect(self.authenticate)

        self.lbl_status = QLabel("Statut : Verrouillé (Privilèges administrateur requis)")
        self.lbl_status.setStyleSheet("color: #e06c75; font-weight: bold;")

        layout_zone1.addWidget(self.btn_auth)
        layout_zone1.addWidget(self.lbl_status)
        layout_zone1.setContentsMargins(9, 2, 9, 2)
        self.group_zone1.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.group_zone1.setLayout(layout_zone1)
        main_layout.addWidget(self.group_zone1)

        # ==========================================
        # ZONE 2 : Sélection cible
        # ==========================================
        self.group_zone2 = QGroupBox(" Zone 2 : Sélection cible ")
        layout_zone2 = QHBoxLayout()

        self.combo_disks = QComboBox()
        self.btn_refresh = QPushButton("Rafraîchir")
        self.btn_refresh.clicked.connect(self.charger_disques)

        layout_zone2.addWidget(QLabel("Disque cible :"))
        layout_zone2.addWidget(self.combo_disks, stretch=1)
        layout_zone2.addWidget(self.btn_refresh)
        self.group_zone2.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.group_zone2.setLayout(layout_zone2)
        main_layout.addWidget(self.group_zone2)
        self.zones_privilegiees.append(self.group_zone2)

        # ==========================================
        # ZONE 3 : Récupération de données
        # (hors zone verrouillée : garde-fous internes à la fenêtre)
        # ==========================================
        self.group_zone3 = QGroupBox(" Zone 3 : Récupération de données ")
        layout_zone3 = QHBoxLayout()

        lbl_krec = QLabel("Fichiers effacés (PhotoRec) et partitions perdues (TestDisk). Destination : toujours sur un autre disque.")
        self.btn_open_krec = QPushButton("Ouvrir la récupération de données")
        self.btn_open_krec.clicked.connect(self.ouvrir_krec)

        layout_zone3.addWidget(lbl_krec, stretch=1)
        layout_zone3.addWidget(self.btn_open_krec)
        layout_zone3.setContentsMargins(9, 2, 9, 2)
        self.group_zone3.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.group_zone3.setLayout(layout_zone3)
        main_layout.addWidget(self.group_zone3)

        # ==========================================
        # ZONE 4 : Clonage de disques ou de partitions
        # (hors zone verrouillée : garde-fous internes à la fenêtre)
        # ==========================================
        self.group_zone4 = QGroupBox(" Zone 4 : Clonage de disques ou de partitions ")
        layout_zone4 = QHBoxLayout()

        lbl_kclone = QLabel("Disque→disque, disque→image, image→disque, partition→partition (ddrescue). ATTENTION : la destination est écrasée.")
        self.btn_open_kclonage = QPushButton("Ouvrir le clonage")
        self.btn_open_kclonage.clicked.connect(self.ouvrir_kclonage)

        layout_zone4.addWidget(lbl_kclone, stretch=1)
        layout_zone4.addWidget(self.btn_open_kclonage)
        layout_zone4.setContentsMargins(9, 2, 9, 2)
        self.group_zone4.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.group_zone4.setLayout(layout_zone4)
        main_layout.addWidget(self.group_zone4)

        # ==========================================
        # ZONE 5 : Tests des disques HDD ou SSD
        # ==========================================
        self.group_zone5 = QGroupBox(" Zone 5 : Tests des disques HDD ou SSD ")
        layout_zone5 = QVBoxLayout()

        layout_z5_n1 = QHBoxLayout()
        self.btn_smart_read = QPushButton("Lecture SMART")
        self.btn_smart_read.clicked.connect(lambda: self.executer_action_smart("read"))
        self.btn_smart_quick = QPushButton("Test SMART rapide")
        self.btn_smart_quick.clicked.connect(lambda: self.executer_action_smart("quick"))
        self.btn_smart_ext = QPushButton("Test SMART étendu")
        self.btn_smart_ext.clicked.connect(lambda: self.executer_action_smart("extended"))

        layout_z5_n1.addWidget(self.btn_smart_read)
        layout_z5_n1.addWidget(self.btn_smart_quick)
        layout_z5_n1.addWidget(self.btn_smart_ext)
        layout_zone5.addLayout(layout_z5_n1)

        layout_z5_n2 = QHBoxLayout()
        self.btn_rep_gen = QPushButton("Rapport général")
        self.btn_rep_gen.clicked.connect(lambda: self.afficher_rapport("general"))
        self.btn_rep_hdd = QPushButton("Rapport crucial HDD")
        self.btn_rep_hdd.clicked.connect(lambda: self.afficher_rapport("hdd"))
        self.btn_rep_ssd = QPushButton("Rapport crucial SSD")
        self.btn_rep_ssd.clicked.connect(lambda: self.afficher_rapport("ssd"))
        self.btn_rep_redige = QPushButton("Rapport rédigé")
        self.btn_rep_redige.clicked.connect(lambda: self.afficher_rapport("redige"))

        layout_z5_n2.addWidget(self.btn_rep_gen)
        layout_z5_n2.addWidget(self.btn_rep_hdd)
        layout_z5_n2.addWidget(self.btn_rep_ssd)
        layout_z5_n2.addWidget(self.btn_rep_redige)
        layout_zone5.addLayout(layout_z5_n2)

        layout_z5_n3 = QHBoxLayout()
        self.btn_outils_disques = QPushButton("🧰 Outils avancés (fsck / surface / SSD-NVMe)")
        self.btn_outils_disques.clicked.connect(self.ouvrir_koutils_disques)
        layout_z5_n3.addWidget(self.btn_outils_disques)
        layout_zone5.addLayout(layout_z5_n3)

        self.group_zone5.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.group_zone5.setLayout(layout_zone5)
        main_layout.addWidget(self.group_zone5)
        self.zones_privilegiees.append(self.group_zone5)

        # ==========================================
        # ZONE 6 : Parcage des têtes HDD
        # ==========================================
        self.group_zone6 = QGroupBox(" Zone 6 : Parcage des têtes HDD ")
        layout_zone6 = QHBoxLayout()

        self.btn_read_park = QPushButton("Lecture réglage")
        self.btn_read_park.clicked.connect(self.lire_reglage_parcage)

        self.txt_park_status = QLineEdit()
        self.txt_park_status.setReadOnly(True)
        self.txt_park_status.setPlaceholderText("État actuel (APM)...")

        self.combo_park = QComboBox()
        self.combo_park.addItems(["Jamais", "300 secondes", "500 secondes"])

        self.btn_apply_park = QPushButton("Réglage")
        self.btn_apply_park.clicked.connect(self.appliquer_reglage_parcage)

        layout_zone6.addWidget(self.btn_read_park)
        layout_zone6.addWidget(self.txt_park_status, stretch=1)
        layout_zone6.addWidget(self.combo_park)
        layout_zone6.addWidget(self.btn_apply_park)
        self.group_zone6.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.group_zone6.setLayout(layout_zone6)
        main_layout.addWidget(self.group_zone6)
        self.zones_privilegiees.append(self.group_zone6)

        # ==========================================
        # ZONE 7 : Partitionnement et Formatage
        # ==========================================
        self.group_zone7 = QGroupBox(" Zone 7 : Partitionnement et Formatage ")
        layout_zone7 = QHBoxLayout()

        self.btn_del_part = QPushButton("Supprimer toutes les partitions")
        self.btn_del_part.setStyleSheet("background-color: #d16969;")
        self.btn_del_part.clicked.connect(self.supprimer_partitions)

        self.combo_format = QComboBox()
        self.combo_format.addItems(["ext4", "NTFS", "FAT32"])
        self.combo_format.setFixedWidth(80)

        self.btn_format = QPushButton("Formater")
        self.btn_format.setFixedWidth(90)
        self.btn_format.clicked.connect(self.lancer_formatage)

        self.lbl_warning_format = QLabel("Êtes vous certain de la sélection du disque ?")
        self.lbl_warning_format.setStyleSheet("font-weight: bold; color: #e5c07b;")

        layout_zone7.addWidget(self.btn_del_part)
        layout_zone7.addWidget(QLabel("Format :"))
        layout_zone7.addWidget(self.combo_format)
        layout_zone7.addWidget(self.btn_format)
        layout_zone7.addWidget(self.lbl_warning_format, stretch=1)
        layout_zone7.setContentsMargins(9, 2, 9, 2)
        self.group_zone7.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.group_zone7.setLayout(layout_zone7)
        main_layout.addWidget(self.group_zone7)
        self.zones_privilegiees.append(self.group_zone7)

        self.combo_disks.currentIndexChanged.connect(self.maj_cible_formatage)
        self.maj_cible_formatage()

        # ==========================================
        # ZONE 8 : Tests des périphériques
        # (hors zone verrouillée : aucun privilège requis)
        # ==========================================
        self.group_zone8 = QGroupBox(" Zone 8 : Tests des périphériques ")
        layout_zone8 = QHBoxLayout()

        lbl_kpv = QLabel("Tests sans privilèges : bus USB, réseau, périphériques d'entrée.")
        self.btn_open_kpv = QPushButton("Lancer les tests périphériques")
        self.btn_open_kpv.clicked.connect(self.ouvrir_kpv)

        layout_zone8.addWidget(lbl_kpv, stretch=1)
        layout_zone8.addWidget(self.btn_open_kpv)
        layout_zone8.setContentsMargins(9, 2, 9, 2)
        self.group_zone8.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.group_zone8.setLayout(layout_zone8)
        main_layout.addWidget(self.group_zone8)

        # ==========================================
        # ZONE 9 : Audit global machine
        # (hors zone verrouillée : fonctionne sans privilèges)
        # ==========================================
        self.group_zone9 = QGroupBox(" Zone 9 : Audit global machine ")
        layout_zone9 = QHBoxLayout()

        lbl_kaudit = QLabel("Score de santé /100, recommandations de sécurité, export HTML, historique.")
        self.btn_open_kaudit = QPushButton("Lancer l'audit global")
        self.btn_open_kaudit.clicked.connect(self.ouvrir_kaudit)

        layout_zone9.addWidget(lbl_kaudit, stretch=1)
        layout_zone9.addWidget(self.btn_open_kaudit)
        layout_zone9.setContentsMargins(9, 2, 9, 2)
        self.group_zone9.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.group_zone9.setLayout(layout_zone9)
        main_layout.addWidget(self.group_zone9)

        # ==========================================
        # ZONE 10 : Comparaison de rapports d'audit
        # (hors zone verrouillée : aucun privilège requis)
        # ==========================================
        self.group_zone10 = QGroupBox(" Zone 10 : Comparaison de rapports d'audit ")
        layout_zone10 = QHBoxLayout()

        lbl_kcomparaison = QLabel("Avant / après : évolution du score /100 et diff des recommandations entre deux audits de la Zone 9.")
        self.btn_open_kcomparaison = QPushButton("Comparer deux audits")
        self.btn_open_kcomparaison.clicked.connect(self.ouvrir_kcomparaison)

        layout_zone10.addWidget(lbl_kcomparaison, stretch=1)
        layout_zone10.addWidget(self.btn_open_kcomparaison)
        layout_zone10.setContentsMargins(9, 2, 9, 2)
        self.group_zone10.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.group_zone10.setLayout(layout_zone10)
        main_layout.addWidget(self.group_zone10)

        # ==========================================
        # ZONE 11 : Vérification des mises à jour et paquets
        # (hors zone verrouillée : fonctionne sans privilèges)
        # ==========================================
        self.group_zone11 = QGroupBox(" Zone 11 : Vérification des mises à jour et paquets ")
        layout_zone11 = QHBoxLayout()

        lbl_kmaj = QLabel("Contrôles APT/DPKG : listes de paquets, mises à jour disponibles, paquets brisés et orphelins.")
        self.btn_open_kmaj = QPushButton("Ouvrir la vérification des mises à jour")
        self.btn_open_kmaj.clicked.connect(self.ouvrir_kmaj)

        layout_zone11.addWidget(lbl_kmaj, stretch=1)
        layout_zone11.addWidget(self.btn_open_kmaj)
        layout_zone11.setContentsMargins(9, 2, 9, 2)
        self.group_zone11.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.group_zone11.setLayout(layout_zone11)
        main_layout.addWidget(self.group_zone11)

        # ==========================================
        # ZONE 12 : Journal d'exécution direct
        # (hors zone verrouillée : fonctionne sans privilèges)
        # ==========================================
        self.group_zone12 = QGroupBox(" Zone 12 : Journal d'exécution direct ")
        layout_zone12 = QHBoxLayout()

        lbl_kjournal = QLabel("Journal système en direct (journalctl) : filtres, priorités, colorisation des erreurs, export.")
        self.btn_open_kjournal = QPushButton("Ouvrir le journal direct")
        self.btn_open_kjournal.clicked.connect(self.ouvrir_kjournal)

        layout_zone12.addWidget(lbl_kjournal, stretch=1)
        layout_zone12.addWidget(self.btn_open_kjournal)
        layout_zone12.setContentsMargins(9, 2, 9, 2)
        self.group_zone12.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.group_zone12.setLayout(layout_zone12)
        main_layout.addWidget(self.group_zone12)

        # ==========================================
        # ZONE 13 : Détection des signes d'alerte système
        # (hors zone verrouillée : fonctionne sans privilèges)
        # ==========================================
        self.group_zone13 = QGroupBox(" Zone 13 : Détection des signes d'alerte système ")
        layout_zone13 = QHBoxLayout()

        lbl_kalertes = QLabel("Scan du journal et du matériel : unités en échec, erreurs disques, OOM, surchauffe, partitions saturées.")
        self.btn_open_kalertes = QPushButton("Scanner les signes d'alerte")
        self.btn_open_kalertes.clicked.connect(self.ouvrir_kalertes)

        layout_zone13.addWidget(lbl_kalertes, stretch=1)
        layout_zone13.addWidget(self.btn_open_kalertes)
        layout_zone13.setContentsMargins(9, 2, 9, 2)
        self.group_zone13.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.group_zone13.setLayout(layout_zone13)
        main_layout.addWidget(self.group_zone13)

        # ==========================================
        # ZONE 14 : Décompte de temps des opérations
        # ==========================================
        self.group_zone14 = QGroupBox(" Zone 14 : Décompte de temps des opérations ")
        layout_zone14 = QHBoxLayout()

        self.lbl_countdown_title = QLabel("Temps restant :")
        self.lbl_countdown_val = QLabel("En attente d'opération...")
        self.lbl_countdown_val.setStyleSheet("color: #98c379; font-weight: bold;")

        layout_zone14.addWidget(self.lbl_countdown_title)
        layout_zone14.addWidget(self.lbl_countdown_val, stretch=1)
        self.group_zone14.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.group_zone14.setLayout(layout_zone14)
        main_layout.addWidget(self.group_zone14)
        self.zones_privilegiees.append(self.group_zone14)

        self.timer_decompte = QTimer(self)
        self.timer_decompte.timeout.connect(self.tic_decompte)
        self.secondes_restantes = 0

        # ==========================================
        # ZONE 15 : Surveillance des capteurs et vitesse du CPU
        # (présentation compacte : les données complètes s'affichent
        # dans une fenêtre dédiée ouverte par le bouton)
        # ==========================================
        self.group_zone15 = QGroupBox(" Zone 15 : Surveillance des capteurs et vitesse du CPU (temps réel) ")
        layout_zone15 = QHBoxLayout()

        lbl_kcapteurs = QLabel("Fréquences CPU, charge, températures, ventilateurs, tensions, puissances et GPU NVIDIA (nvidia-smi) — relevés en direct.")
        self.btn_open_kcapteurs = QPushButton("▶ Démarrer la surveillance")
        self.btn_open_kcapteurs.clicked.connect(self.ouvrir_kcapteurs)

        layout_zone15.addWidget(lbl_kcapteurs, stretch=1)
        layout_zone15.addWidget(self.btn_open_kcapteurs)
        layout_zone15.setContentsMargins(9, 2, 9, 2)
        self.group_zone15.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.group_zone15.setLayout(layout_zone15)
        main_layout.addWidget(self.group_zone15)

        # ==========================================
        # ZONE 16 : Signature / crédits
        # (aucune fonction active : présentation uniquement)
        # ==========================================
        self.group_zone16 = QGroupBox(" Zone 16 : Conception ")
        layout_zone16 = QHBoxLayout()

        lbl_kredits = QLabel("Conception oliveval17-max with Mistral Vibe Code")
        lbl_kredits.setAlignment(Qt.AlignCenter)
        lbl_kredits.setStyleSheet("color: #7a8190; font-style: italic; font-size: 11px;")

        layout_zone16.addWidget(lbl_kredits, stretch=1)
        layout_zone16.setContentsMargins(9, 2, 9, 2)
        self.group_zone16.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.group_zone16.setLayout(layout_zone16)
        main_layout.addWidget(self.group_zone16)

        main_layout.addStretch(1)
        self.set_zones_enabled(False)

        # Déverrouillage immédiat si KareDiag a été élevé au lancement
        if est_root():
            self.btn_auth.setEnabled(False)
            self.lbl_status.setText("Statut : Mode Administrateur actif (authentification unique)")
            self.lbl_status.setStyleSheet("color: #98c379; font-weight: bold;")
            self.set_zones_enabled(True)
            self.charger_disques()

    # ==========================================
    # OUTILS DE LA FENÊTRE PRINCIPALE
    # ==========================================
    def set_zones_enabled(self, enabled):
        for zone in self.zones_privilegiees:
            zone.setEnabled(enabled)

    # ==========================================
    # ZONE 1 : CONNEXION SU
    # ==========================================
    def authenticate(self):
        # Secours uniquement : si l'app tourne en mode restreint
        # (élévation refusée au lancement).
        try:
            res = subprocess.run(["pkexec", "true"], capture_output=True, text=True)
            if res.returncode == 0:
                self.lbl_status.setText("Statut : Débloqué (Mode Administrateur actif)")
                self.lbl_status.setStyleSheet("color: #98c379; font-weight: bold;")
                self.btn_auth.setEnabled(False)
                self.set_zones_enabled(True)
                self.charger_disques()
            else:
                QMessageBox.warning(
                    self, "Authentification refusée",
                    "Authentification PolicyKit annulée ou échouée.\n"
                    "Les zones privilégiées (2, 5, 6, 7 et 14) restent verrouillées."
                )
        except FileNotFoundError:
            QMessageBox.critical(self, "Erreur", "pkexec est introuvable sur ce système.")
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"PolicyKit indisponible :\n{e}")

    # ==========================================
    # ZONE 2 : LISTE DES DISQUES
    # ==========================================
    def charger_disques(self):
        disque_avant = self.combo_disks.currentData()
        self.combo_disks.clear()
        try:
            cmd = ["lsblk", "-d", "-o", "NAME,MODEL,SIZE,ROTA,MOUNTPOINT,SERIAL", "--json"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)
            disques = data.get("blockdevices", [])

            count = 0
            for d in disques:
                nom = f"/dev/{d.get('name', 'inconnu')}"
                modele = (d.get('model') or "Modèle inconnu").strip()
                taille = d.get('size', 'N/A')
                rota = d.get('rota')
                if rota is True:
                    type_disque = "HDD SATA"
                elif rota is False:
                    type_disque = "SSD"
                else:
                    type_disque = "Type inconnu"
                mount = d.get('mountpoint')
                mount_str = f"Monté sur : {mount}" if mount else "Non monté"
                serial = (d.get('serial') or "S/N inconnu").strip()

                ligne_affichage = f"{nom} - {modele} ({type_disque}) [S/N: {serial}] - {taille} - {mount_str}"
                self.combo_disks.addItem(ligne_affichage, nom)
                count += 1

            if count == 0:
                self.combo_disks.addItem("Aucun disque détecté")
        except Exception:
            self.combo_disks.addItem("Erreur lors de la lecture des disques")

        # Préserver la sélection de l'utilisateur à travers les rafraîchissements
        idx = self.combo_disks.findData(disque_avant)
        if idx >= 0:
            self.combo_disks.setCurrentIndex(idx)
        self.maj_cible_formatage()

    def maj_cible_formatage(self):
        disque = self.extraire_chemin_disque()
        if disque:
            self.lbl_warning_format.setText(f"Cible sélectionnée : {disque}")
            self.lbl_warning_format.setStyleSheet("font-weight: bold; color: #e5c07b;")

    def extraire_chemin_disque(self):
        return self.combo_disks.currentData()

    def contient_systeme(self, disque):
        cible = os.path.basename(disque)
        try:
            res = subprocess.run(
                ["lsblk", "-r", "-no", "PKNAME,MOUNTPOINT"],
                capture_output=True, text=True
            )
            for ligne in res.stdout.splitlines():
                parts = ligne.split()
                if len(parts) == 2 and parts[1] == "/" and parts[0] == cible:
                    return True
        except Exception:
            pass
        return False

    def verifier_cible_destructive(self, disque):
        if self.contient_systeme(disque):
            QMessageBox.critical(
                self, "Opération interdite",
                f"{disque} contient le système d'exploitation actif.\n"
                "Cette opération destructrice est refusée."
            )
            return False
        return True

    def demonter_partitions(self, disque):
        """Démonte toutes les partitions et désactive le swap du disque cible.

        Renvoie la liste des erreurs (vide si tout est démonté proprement).
        """
        return demonter_destination(disque, log_fn=self.lbl_warning_format.setText)

    # ==========================================
    # ZONE 7 : SUPPRESSION / FORMATAGE
    # ==========================================
    def supprimer_partitions(self):
        disque = self.extraire_chemin_disque()
        if not disque:
            QMessageBox.warning(self, "Erreur", "Veuillez sélectionner un disque valide.")
            return

        if not self.verifier_cible_destructive(disque):
            return

        confirmation = QMessageBox.question(
            self, "Confirmation critique",
            f"Êtes-vous SÛR de vouloir supprimer TOUTES les partitions de {disque} ?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if confirmation == QMessageBox.Yes:
            erreurs = self.demonter_partitions(disque)
            if erreurs:
                QMessageBox.critical(
                    self, "Opération interdite",
                    "Impossible de démonter certaines partitions (en cours d'utilisation) :\n"
                    + "\n".join(erreurs) + "\n\nOpération annulée."
                )
                return
            try:
                self.lbl_warning_format.setText("Suppression en cours...")
                QApplication.processEvents()
                subprocess.run(["udevadm", "settle"], capture_output=True, text=True, timeout=30)
                cmd = prefixe_privilege() + [
                    "bash", "-c",
                    f"wipefs -a {disque} && wipefs -a {disque}?* 2>/dev/null; partprobe {disque}"
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    self.charger_disques()
                    verif = subprocess.run(
                        ["lsblk", "-rno", "NAME", disque], capture_output=True, text=True
                    )
                    reste = max(0, len(verif.stdout.splitlines()) - 1)
                    if reste == 0:
                        self.lbl_warning_format.setText("Disque vierge (aucune partition)")
                        self.lbl_warning_format.setStyleSheet("font-weight: bold; color: #98c379;")
                        QMessageBox.information(
                            self, "Succès", f"Partitions supprimées sur {disque}.\nDisque totalement vierge."
                        )
                    else:
                        self.lbl_warning_format.setText(
                            f"Attention : {reste} partition(s) encore détectée(s)"
                        )
                        self.lbl_warning_format.setStyleSheet("font-weight: bold; color: #e5c07b;")
                else:
                    self.lbl_warning_format.setText("Échec de la suppression")
                    self.lbl_warning_format.setStyleSheet("font-weight: bold; color: #e06c75;")
                    QMessageBox.critical(self, "Erreur", f"Échec :\n{result.stderr}")
            except Exception as e:
                QMessageBox.critical(self, "Erreur système", str(e))

    def lancer_formatage(self):
        disque = self.extraire_chemin_disque()
        if not disque:
            QMessageBox.warning(self, "Erreur", "Veuillez sélectionner un disque cible valide.")
            return

        if not self.verifier_cible_destructive(disque):
            return

        format_choisi = self.combo_format.currentText()
        reglages = {
            "ext4": {"outil": "mkfs.ext4", "paquet": "e2fsprogs", "type": "ext4",
                     "mkfs": 'mkfs.ext4 -F -L KAREDIAG "/dev/$part"'},
            "NTFS": {"outil": "mkfs.ntfs", "paquet": "ntfs-3g", "type": "ntfs",
                     "mkfs": 'mkfs.ntfs -f -L KAREDIAG "/dev/$part"'},
            "FAT32": {"outil": "mkfs.fat", "paquet": "dosfstools", "type": "fat32",
                      "mkfs": 'mkfs.fat -F32 -n KAREDIAG "/dev/$part"'},
        }
        if format_choisi not in reglages:
            return
        reglage = reglages[format_choisi]

        if not shutil.which("parted"):
            QMessageBox.critical(
                self, "Outil manquant",
                "parted est introuvable sur ce système.\n"
                "Installez le paquet requis :\n\nsudo apt install parted"
            )
            return
        if not shutil.which(reglage["outil"]):
            QMessageBox.critical(
                self, "Outil manquant",
                f"{reglage['outil']} est introuvable sur ce système.\n"
                f"Installez le paquet requis :\n\nsudo apt install {reglage['paquet']}"
            )
            return

        confirmation = QMessageBox.question(
            self, "Confirmation de formatage",
            f"Voulez-vous vraiment formater {disque} en {format_choisi} ?\n\n"
            "Attention : tout le disque sera effacé, puis une table de partitions GPT\n"
            "et une partition unique recouvrant tout le disque seront créées.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if confirmation == QMessageBox.Yes:
            try:
                erreurs = self.demonter_partitions(disque)
                if erreurs:
                    QMessageBox.critical(
                        self, "Opération interdite",
                        "Impossible de démonter certaines partitions (en cours d'utilisation) :\n"
                        + "\n".join(erreurs) + "\n\nFormatage annulé."
                    )
                    return
                self.lbl_warning_format.setText("Formatage en cours...")
                self.lbl_warning_format.setStyleSheet("font-weight: bold; color: #e5c07b;")
                QApplication.processEvents()
                disque_sh = shlex.quote(disque)
                script = f"""set -e
DISQUE={disque_sh}
wipefs -a "$DISQUE"
wipefs -a "$DISQUE"?* 2>/dev/null || true
partprobe "$DISQUE"
udevadm settle
parted -s "$DISQUE" mklabel gpt
parted -s "$DISQUE" mkpart "KareDiag" {reglage["type"]} 1MiB 100%
udevadm settle
partprobe "$DISQUE"
part=""
essai=0
while [ $essai -lt 20 ]; do
    part=$(lsblk -rno NAME "$DISQUE" | sed -n '2p' || true)
    if [ -n "$part" ]; then
        break
    fi
    sleep 0.5
    essai=$((essai + 1))
done
[ -n "$part" ] || exit 3
{reglage["mkfs"]}
sync
udevadm settle
"""
                result = subprocess.run(
                    prefixe_privilege() + ["bash", "-c", script],
                    capture_output=True, text=True, timeout=1800
                )
                if result.returncode == 0:
                    self.charger_disques()
                    part_info = ""
                    try:
                        verif = subprocess.run(
                            ["lsblk", "-rno", "NAME", disque], capture_output=True, text=True
                        )
                        lignes = verif.stdout.splitlines()
                        if len(lignes) > 1:
                            part_info = f"\nPartition créée : /dev/{lignes[1].strip()}"
                    except Exception:
                        pass
                    self.lbl_warning_format.setText("Opérations terminées")
                    self.lbl_warning_format.setStyleSheet("font-weight: bold; color: #98c379;")
                    QMessageBox.information(
                        self, "Succès",
                        f"Formatage réussi en {format_choisi}.{part_info}"
                    )
                else:
                    self.lbl_warning_format.setText("Échec du formatage")
                    self.lbl_warning_format.setStyleSheet("font-weight: bold; color: #e06c75;")
                    raison = result.stderr.strip() or result.stdout.strip() or "Raison inconnue"
                    if result.returncode == 3:
                        raison = "La partition n'a pas pu être détectée après le partitionnement."
                    QMessageBox.critical(self, "Erreur", f"Échec du formatage en {format_choisi} :\n{raison}")
            except Exception as e:
                self.lbl_warning_format.setText("Échec du formatage")
                self.lbl_warning_format.setStyleSheet("font-weight: bold; color: #e06c75;")
                QMessageBox.critical(self, "Erreur système", str(e))

    # ==========================================
    # ZONE 5 : SMART
    # ==========================================
    def verifier_smartctl(self):
        if shutil.which("smartctl"):
            return True
        QMessageBox.critical(
            self, "Outil manquant",
            "smartctl est introuvable sur ce système.\n"
            "Installez le paquet requis :\n\nsudo apt install smartmontools"
        )
        return False

    def executer_action_smart(self, action):
        disque = self.extraire_chemin_disque()
        if not disque:
            QMessageBox.warning(self, "Erreur", "Veuillez sélectionner un disque cible.")
            return
        if not self.verifier_smartctl():
            return

        try:
            if action == "read":
                cmd = prefixe_privilege() + ["smartctl", "-A", disque]
                res = subprocess.run(cmd, capture_output=True, text=True)
                if not res.stdout:
                    QMessageBox.critical(
                        self, "Erreur SMART",
                        res.stderr or "smartctl n'a retourné aucune donnée pour ce disque."
                    )
                    return
                self.ouvrir_fenetre_rapport(f"Lecture SMART - {disque}", res.stdout)
            elif action == "quick":
                cmd = prefixe_privilege() + ["smartctl", "-t", "short", disque]
                res = subprocess.run(cmd, capture_output=True, text=True)
                if not res.stdout:
                    QMessageBox.critical(
                        self, "Erreur SMART",
                        res.stderr or "Impossible de lancer le test rapide."
                    )
                    return
                self.demarrer_decompte(self.extraire_duree_test(res.stdout, 2))
                QMessageBox.information(self, "Test SMART Rapide", f"Test lancé sur {disque}.\n{res.stdout}")
            elif action == "extended":
                cmd = prefixe_privilege() + ["smartctl", "-t", "long", disque]
                res = subprocess.run(cmd, capture_output=True, text=True)
                if not res.stdout:
                    QMessageBox.critical(
                        self, "Erreur SMART",
                        res.stderr or "Impossible de lancer le test étendu."
                    )
                    return
                self.demarrer_decompte(self.extraire_duree_test(res.stdout, 120))
                QMessageBox.information(self, "Test SMART Étendu", f"Test long lancé sur {disque}.\n{res.stdout}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Impossible d'exécuter la commande SMART :\n{e}")

    def extraire_duree_test(self, sortie_smartctl, valeur_defaut_minutes):
        correspondance = re.search(r"Please wait (\d+) minutes", sortie_smartctl)
        if correspondance:
            return int(correspondance.group(1))
        return valeur_defaut_minutes

    def demarrer_decompte(self, minutes):
        self.secondes_restantes = int(minutes * 60)
        self.tic_decompte()
        self.timer_decompte.start(1000)

    def tic_decompte(self):
        if self.secondes_restantes <= 0:
            self.timer_decompte.stop()
            self.lbl_countdown_val.setText(
                "Test SMART terminé — lancez « Lecture SMART » pour consulter les résultats."
            )
            return
        minutes, secondes = divmod(self.secondes_restantes, 60)
        self.lbl_countdown_val.setText(f"{minutes:02d}:{secondes:02d}")
        self.secondes_restantes -= 1

    # ==========================================
    # ZONE 15 : OUVERTURE DE LA SURVEILLANCE
    # ==========================================
    def ouvrir_kcapteurs(self):
        self.fenetre_kcapteurs = KCapteursWindow(self)
        self.fenetre_kcapteurs.exec_()

    def afficher_rapport(self, type_rapport):
        disque = self.extraire_chemin_disque()
        if not disque:
            QMessageBox.warning(self, "Erreur", "Veuillez sélectionner un disque cible.")
            return
        if not self.verifier_smartctl():
            return

        try:
            cmd = prefixe_privilege() + ["smartctl", "-a", disque]
            res = subprocess.run(cmd, capture_output=True, text=True)
            brut = res.stdout

            if not brut:
                QMessageBox.critical(
                    self, "Erreur SMART",
                    res.stderr or "smartctl n'a retourné aucune donnée pour ce disque."
                )
                return

            if type_rapport == "general":
                titre = f"Rapport Général SMART - {disque}"
                contenu = brut

            elif type_rapport == "hdd":
                titre = f"Rapport Crucial HDD (IDs 5, 187, 188, 194, 197, 198) - {disque}"
                lignes_filtrees = [
                    "ID# ATTRIBUTE_NAME          FLAG     VALUE WORST THRESH TYPE      UPDATED  WHEN_FAILED RAW_VALUE",
                    "-" * 95
                ]
                for ligne in brut.splitlines():
                    if any(ligne.strip().startswith(x) for x in ["5 ", "197 ", "198 ", "187 ", "188 ", "194 ", "220 "]):
                        lignes_filtrees.append(ligne)
                contenu = "\n".join(lignes_filtrees) if len(lignes_filtrees) > 2 else "Aucun attribut HDD critique trouvé ou disque de type SSD."

            elif type_rapport == "ssd":
                titre = f"Rapport Crucial SSD (IDs 3, 5, 177, 231, 232, 233) - {disque}"
                lignes_filtrees = [
                    "ID# ATTRIBUTE_NAME          FLAG     VALUE WORST THRESH TYPE      UPDATED  WHEN_FAILED RAW_VALUE",
                    "-" * 95
                ]
                for ligne in brut.splitlines():
                    if any(ligne.strip().startswith(x) for x in ["5 ", "3 ", "177 ", "231 ", "232 ", "233 "]):
                        lignes_filtrees.append(ligne)
                contenu = "\n".join(lignes_filtrees) if len(lignes_filtrees) > 2 else "Attributs SSD spécifiques non trouvés dans le rapport brut."

            elif type_rapport == "redige":
                titre = f"Rapport Rédigé d'Analyse - {disque}"
                cmd_health = prefixe_privilege() + ["smartctl", "-H", disque]
                res_health = subprocess.run(cmd_health, capture_output=True, text=True)

                etat_sante = "Inconnu"
                if "PASSED" in res_health.stdout:
                    etat_sante = "BON (Le disque a réussi l'autotest SMART global)"
                elif "FAILED" in res_health.stdout:
                    etat_sante = "CRITIQUE (Défaillance SMART détectée ! Risque de panne imminent)"

                contenu = f"""RAPPORT D'EXPERTISE KAREDIAG - ANALYSE DE SANTÉ
==================================================
Disque analysé : {disque}
Date / Contexte : Analyse Kaisen Linux - KareDiag

1. ÉTAT DE SANTÉ GÉNÉRAL :
- Bilan SMART global : {etat_sante}

2. AVIS TECHNIQUE :
- Le système d'auto-surveillance (SMART) ne signale pas d'anomalie immédiate si l'état est au vert.
- En cas de secteurs réalloués détectés (ID 05), surveillez l'évolution de leur compteur de près.

3. UTILISATION RECOMMANDÉE :
- Si l'état est BON : Le disque est apte pour l'exploitation standard, le stockage ou le clonage forensic.
- Si l'état est CRITIQUE : Évitez toute écriture intensive. Procédez immédiatement à une sauvegarde ou une image disque avant la panne totale.
==================================================
"""
            self.ouvrir_fenetre_rapport(titre, contenu)
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Erreur lors de la génération du rapport :\n{e}")

    # ==========================================
    # ZONE 6 : PARCAGE DES TÊTES
    # ==========================================
    def lire_reglage_parcage(self):
        disque = self.extraire_chemin_disque()
        if not disque:
            QMessageBox.warning(self, "Erreur", "Veuillez sélectionner un disque cible.")
            return

        try:
            cmd = prefixe_privilege() + ["hdparm", "-B", disque]
            res = subprocess.run(cmd, capture_output=True, text=True)

            if res.returncode != 0 or "APM" not in res.stdout:
                self.txt_park_status.setText("Fonction non supportée (SSD / NVMe / Non géré)")
            else:
                self.txt_park_status.setText(res.stdout.strip())
        except Exception:
            self.txt_park_status.setText("Erreur de lecture")

    def appliquer_reglage_parcage(self):
        disque = self.extraire_chemin_disque()
        if not disque:
            QMessageBox.warning(self, "Erreur", "Veuillez sélectionner un disque cible.")
            return

        choix = self.combo_park.currentText()

        # hdparm -S travaille en unités de 5 secondes
        if choix == "Jamais":
            valeur_s = "0"
        elif choix == "300 secondes":
            valeur_s = "60"
        else:
            valeur_s = "100"

        try:
            cmd = prefixe_privilege() + ["hdparm", "-S", valeur_s, disque]
            res = subprocess.run(cmd, capture_output=True, text=True)

            if res.returncode == 0:
                self.txt_park_status.setText(f"Réglage appliqué : {choix}")
                QMessageBox.information(
                    self, "Succès",
                    f"Réglage de parcage ({choix}) appliqué avec succès sur {disque}."
                )
            else:
                self.txt_park_status.setText("Fonction non supportée (SSD / NVMe / Non géré)")
                QMessageBox.warning(
                    self, "Avertissement",
                    "Le disque cible (ex: SSD) ne prend pas en charge le minuteur de veille."
                )
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Impossible d'appliquer le réglage :\n{e}")

    # ==========================================
    # ZONES 3, 4, 8 et 9 : OUVERTURE DES FENÊTRES
    # ==========================================
    def ouvrir_kpv(self):
        self.fenetre_kpv = KPVWindow(self)
        self.fenetre_kpv.exec_()

    def ouvrir_krec(self):
        self.fenetre_krec = KRecuperationWindow(self, self.extraire_chemin_disque())
        self.fenetre_krec.exec_()

    def ouvrir_kclonage(self):
        self.fenetre_kclonage = KClonageWindow(self, self.extraire_chemin_disque())
        self.fenetre_kclonage.exec_()

    def ouvrir_koutils_disques(self):
        self.fenetre_koutils_disques = KOutilsDisquesWindow(self, self.extraire_chemin_disque())
        self.fenetre_koutils_disques.exec_()

    def ouvrir_kaudit(self):
        self.fenetre_kaudit = KAuditWindow(self, self.extraire_chemin_disque())
        self.fenetre_kaudit.exec_()

    def ouvrir_kcomparaison(self):
        self.fenetre_kcomparaison = KAuditCompareWindow(self)
        self.fenetre_kcomparaison.exec_()

    def ouvrir_kmaj(self):
        self.fenetre_kmaj = KMAJWindow(self)
        self.fenetre_kmaj.exec_()

    def ouvrir_kjournal(self):
        self.fenetre_kjournal = KJournalWindow(self)
        self.fenetre_kjournal.exec_()

    def ouvrir_kalertes(self):
        self.fenetre_kalertes = KAlertesWindow(self)
        self.fenetre_kalertes.exec_()

    def ouvrir_fenetre_rapport(self, titre, texte):
        self.fenetre_rapport = RapportWindow(titre, texte)
        self.fenetre_rapport.exec_()


if __name__ == "__main__":
    try:
        # Authentification unique : une seule demande PolicyKit au lancement.
        # Si l'utilisateur refuse ou si l'élévation échoue, l'app continue
        # en mode restreint (Zones 3, 4, 8, 9 et 10 ouvertes sans privilèges).
        if os.geteuid() != 0:
            code = elever_application()
            if code == 0:
                sys.exit(0)

        app = QApplication(sys.argv)
        window = KDiskApp()
        window.show()
        sys.exit(app.exec_())
    except SystemExit:
        raise
    except Exception:
        import traceback
        err = traceback.format_exc()
        try:
            if QApplication.instance() is None:
                app = QApplication(sys.argv)
            QMessageBox.critical(None, "Erreur fatale KareDiag", err)
        except Exception:
            pass
        with open(os.path.expanduser("~/karediag_erreur.txt"), "w") as f:
            f.write(err)
        sys.exit(1)
