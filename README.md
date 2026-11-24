# 🩺 KareDiag

**KareDiag V-8.4.1** — Logiciel de maintenance, de diagnostic et de sauvetage de disques pour Linux, en un seul fichier Python (`karediag.py`), interface 100 % française à thème sombre.

*Conception : oliveval17-max avec Mistral Vibe Code — optimisé pour Kaisen Linux 🇫🇷*

> KareDiag est conçu pour **Kaisen Linux** (base Debian) et validé au quotidien sur **Linux Mint**. Il fonctionne sur n'importe quelle distribution à base de Debian/Ubuntu disposant des prérequis ci-dessous. L'interface s'adapte à votre système : la distribution réelle est détectée et affichée dans le titre de la fenêtre, et la Zone 15 s'adapte à votre carte mère et à votre matériel (capteurs génériques + configuration automatique par modèle de puce, GPU NVIDIA inclus).

---

## ⚠️ Avertissement important

Certaines zones sont **destructrices par nature** : le clonage (Zone 4) **écrase systématiquement la destination** (disque ou image), le formatage (Zone 5) efface vos données, la suppression de partitions est irréversible. Relisez toujours la cible sélectionnée avant de confirmer. Aucune sauvegarde ne remplace un utilisateur attentif !

---

## 🧰 Les 16 zones

| Zone | Nom | Privèges | Description |
|------|-----|----------|-------------|
| 1 | Connexion SU | — | Authentification PolicyKit **à la demande** : les zones protégées se débloquent quand vous en avez besoin |
| 2 | Sélection cible | 🔒 | Choix du disque ou de la partition à traiter, rafraîchissement automatique |
| 3 | Récupération de données | à la demande | Fichiers effacés (PhotoRec) et partitions perdues (TestDisk), destination toujours sur un autre disque |
| 4 | Clonage disques/partitions | à la demande | Disque→disque, disque→image, image→disque, partition→partition (ddrescue), avec **empreinte SHA-256** calculée/vérifiée automatiquement après clonage |
| 5 | Tests et formatage | 🔒 | Lecture et tests SMART (rapide, étendu, rapports rédigés) + dépannage avancé : réparation (fsck), test de surface, SSD/NVMe, formatage |
| 6 | Parcage des têtes HDD | 🔒 | Lecture et réglage du niveau APM pour les disques mécaniques |
| 7 | Partitionnement et formatage | 🔒 | Partitionnement et formatage cible (système de fichiers choisi dans la fenêtre déroulante) |
| 8 | Tests des périphériques | non | Bus USB, réseau, périphériques d'entrée |
| 9 | Audit global machine | à la demande | Score de santé /100, recommandations de sécurité, export HTML, historique |
| 10 | Comparaison de rapports d'audit | non | Évolution avant/après du score et des recommandations entre deux audits |
| 11 | Vérification des mises à jour et paquets | à la demande | Contrôles APT/DPKG : listes, mises à jour disponibles, paquets brisés et orphelins |
| 12 | Journal d'exécution direct | non | Journal système en direct (journalctl) : filtres, priorités, colorisation, export |
| 13 | Détection des signes d'alerte | non | Scan du journal et du matériel : unités en échec, erreurs de disques, OOM, surchauffe, partitions saturées — filtre intelligent des faux positifs Live ISO (casper/live-boot) et des bruits bénins du noyau |
| 14 | Décompte de temps des opérations | 🔒 | Suivi du temps restant de l'opération en cours |
| 15 | Surveillance capteurs et CPU | non | **Temps réel** : fréquences des cœurs, charge, températures, ventilateurs, tensions (annuaire par puce + `/etc/sensors3.conf`), puissances et **GPU NVIDIA** (nvidia-smi). Fenêtre dédiée + export CSV |
| 16 | Signature | non | Crédits et version (aucune fonction active) |

Les zones 🔒 (2, 5, 6, 7 et 14) se débloquent après authentification Zone 1 ; pour les zones « à la demande » (3, 4, 9, 11 ainsi que certaines actions avancées), KareDiag invoque PolicyKit au moment de la commande sensible. Aucune authentification pour les zones « non ».

---

## 📥 Installation

### Méthode 1 — Téléchargement simple (fichier unique)

1. Téléchargez le **ZIP** (bouton vert **Code ▾ → Download ZIP**) et extrayez-le.
2. Dans un terminal (sans sudo) :

```bash
python3 karediag.py
```

3. C'est tout ! **Au premier lancement**, KareDiag installe automatiquement :
   - son **icône** dans `~/.local/share/icons/hicolor/128x128/apps/` ;
   - un **lanceur** dans `~/.local/share/applications/` → « KareDiag » apparaît ensuite dans le **menu Applications** de votre bureau (Mint/Cinnamon et autres), avec sa propre icône. Vous pouvez alors l'épingler au bureau ou à la barre des tâches.

> 💡 L'icône du fichier `karediag.py` dans le gestionnaire de fichiers reste l'icône Python : c'est l'association de type de fichier de votre système, ce n'est pas un bug. C'est le **lanceur** qui porte l'icône KareDiag.

KareDiag n'a **jamais besoin** d'être lancé avec sudo : il demande lui-même les privilèges via PolicyKit quand une zone les exige.

### Méthode 2 — Paquet Debian (.deb)

Construisez puis installez le paquet (voir [deb/README.md](deb/README.md)) :

```bash
./deb/construire_deb.sh
sudo apt install ./karediag_8.4.1_all.deb
```

Le paquet installe tout au niveau système (`/usr/bin/karediag`, icône et lanceur partagés).

### Prérequis

Debian/Ubuntu/Mint/Kaisen :

```bash
sudo apt install python3 python3-pyqt5 policykit-1 smartmontools \
    gddrescue testdisk hdparm lm-sensors nvme-cli parted util-linux \
    usbutils pciutils
```

- **GPU NVIDIA** (facultatif) : si les pilotes NVIDIA sont installés, `nvidia-smi` fournit température, ventilateur, charge, puissance et mémoire vidéo en Zone 15 — sans lui, la section GPU est simplement absente.
- **lm-sensors** est facultatif mais recommandé (détection complète des ventilateurs et tensions, voir ci-dessous).

---

## 🌡️ Capteurs : acter la détection de sa carte mère (une fois)

Pour les ventilateurs et tensions, le mieux est d'exécuter une fois :

```bash
sudo sensors-detect
```

Répondez `y` aux propositions par défaut. À la fin, la liste des modules nécessaires s'affiche (par exemple `coretemp` + `it87` sur un chipset **ITE IT8620E** comme un Gigabyte H97-HD3) et `sensors-detect` peut les ajouter automatiquement à `/etc/modules`. Chargez-les immédiatement :

```bash
sudo modprobe coretemp it87
```

Rechargez KareDiag : la Zone 15 remonte températures, ventilateurs et tensions. **Elle s'adapte à votre matériel** :

- lecture universelle de `/sys/class/hwmon` (cartes mère toutes marques) ;
- **annuaire embarqué par modèle de puce** (`RAILS_PAR_PUCE`) : quand la puce est connue (ex. ITE IT8620E, ratios décodés pour +12 V, +5 V, +3,3 V, Vcore…), les libellés et ratios exacts sont appliqués automatiquement ;
- les tensions hors de ±10 % de leur valeur nominale sont affichées brutes avec préfixe, jamais étiquetées à tort ;
- **personnalisable** : vos propres sections `chip "..."` de `/etc/sensors3.conf` (labels et `compute`) sont prioritaires sur l'annuaire embarqué — aucune modification de code nécessaire ;
- les sondes fantômes (typiquement −128 °C) sont filtrées, les ventilateurs à 0 tr/min ignorés.

---

## ❓ Questions fréquentes

**La Zone 13 signale-t-elle beaucoup d'erreurs sur une clé USB Live ISO ?** Non : les unités systemd propres aux sessions Live (`casper`, `live-boot`, etc.) sont filtrées comme faux positifs, ainsi que quelques messages bénins du noyau (voir aussi le symbole de service devant les unités, correctement retiré).

**L'authentification est demandée à chaque lancement ?** Oui — une seule fois par session via PolicyKit, et uniquement si vous démarrez sans privilèges. Vous pouvez aussi la refuser : KareDiag continue alors en mode restreint avec les zones non privilégiées.

**J'ai lancé KareDiag avec sudo et le lanceur ne s'installe pas.** C'est voulu : avec sudo, KareDiag refuse d'écrire dans vos fichiers personnels. Lancez-le **sans sudo** — il s'élève lui-même proprement.

**Mon GPU NVIDIA n'apparaît pas.** Vérifiez `nvidia-smi` en terminal. Sans pilote NVIDIA installé, la section GPU est absente de la Zone 15 (comportement normal).

---

## 🛠️ Développement

- **Un seul fichier** : `karediag.py` (~5 500 lignes, PyQt5, aucune dépendance Python externe).
- Chaque zone est une classe `QDialog` dédiée (`KRcupWindow`, `KClonageWindow`, `KCapteursWindow`, …) ouverte depuis la fenêtre principale.
- L'**icône et le drapeau sont dessinés en pur code** (QPainter, aucun fichier binaire embarqué) ; l'icône reproduit fidèlement le SVG de conception (écran sombre, « K » cyan, pastille verte).
- Les privilèges : élévation unique au lancement (`elever_application` via pkexec) ou authentification à la demande (Zone 1) ; en mode élevé, l'installation du lanceur vise l'utilisateur d'origine (`PKEXEC_UID`).

### Feuille de route

- [ ] Montage **en lecture seule** d'une image disque (explorer/extraire sans re-cloner) — en suspens
- [ ] Distribuer le `.deb` via les pages GitHub Releases

---

## ✒️ Crédits

KareDiag — **oliveval17-max avec Mistral Vibe Code** : KareDiag V-8.4.1 optimisé pour Kaisen Linux 🇫🇷
