# minia-lab

Outils de veille et de test de miniatures YouTube.

```bash
pip install -r requirements.txt
python3 veille.py          # meilleures et pires vidéos des chaînes de chaines.txt → sortie/planche.html
python3 decouverte.py      # petites chaînes qui ont percé, d'après requetes.txt → sortie/decouverte.html
python3 test_minia.py ma_minia.png   # planche de contrôle → sortie/tests/
```

Il faut que l'environnement autorise `www.youtube.com` et `i.ytimg.com`.
`test_minia.py` place la miniature au milieu de celles téléchargées par `veille.py` : lance la veille au moins une fois avant.
