#!/bin/sh
# Construit le paquet Debian KareDiag : karediag_<version>_all.deb
# Prérequis : dpkg-deb (présent sur toute distribution Debian) ; python3.
# La version est lue automatiquement depuis karediag.py (VERSION_APPLICATION).
set -e

RACINE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RACINE"

VERSION="$(python3 -c "
import re
with open('karediag.py', encoding='utf-8') as f:
    source = f.read()
m = re.search(r'VERSION_APPLICATION\s*=\s*\"([^\"]+)\"', source)
print(m.group(1) if m else '')
")"
if [ -z "$VERSION" ]; then
    echo "Erreur : VERSION_APPLICATION introuvable dans karediag.py" >&2
    exit 1
fi

CONSTRUIRE="deb/construire"
PAQUET="karediag_${VERSION}_all.deb"

rm -rf "$CONSTRUIRE"
mkdir -p "$CONSTRUIRE/DEBIAN" \
         "$CONSTRUIRE/usr/bin" \
         "$CONSTRUIRE/usr/share/karediag" \
         "$CONSTRUIRE/usr/share/applications" \
         "$CONSTRUIRE/usr/share/doc/karediag" \
         "$CONSTRUIRE/usr/share/icons/hicolor"

install -m 644 karediag.py \
    "$CONSTRUIRE/usr/share/karediag/karediag.py"
install -m 755 deb/lanceur.sh "$CONSTRUIRE/usr/bin/karediag"
install -m 644 deb/karediag.desktop \
    "$CONSTRUIRE/usr/share/applications/karediag.desktop"
install -m 644 README.md "$CONSTRUIRE/usr/share/doc/karediag/README.md"
install -m 644 deb/copyright \
    "$CONSTRUIRE/usr/share/doc/karediag/copyright"

python3 deb/generer_icone.py --dossier \
    "$CONSTRUIRE/usr/share/icons/hicolor"

sed "s/__VERSION__/$VERSION/" deb/controle \
    > "$CONSTRUIRE/DEBIAN/control"
install -m 755 deb/postinst "$CONSTRUIRE/DEBIAN/postinst"

dpkg-deb --root-owner-group --build "$CONSTRUIRE" "$PAQUET"
rm -rf "$CONSTRUIRE"

echo ""
echo "Paquet construit : $(pwd)/$PAQUET"
echo "Installation    : sudo apt install ./$PAQUET"
echo "Désinstallation : sudo apt remove karediag"
