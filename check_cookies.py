import sqlite3, os

roots = {
    'Chrome-Default': r'C:\Users\sakiko\AppData\Local\Google\Chrome\User Data\Default',
    'Chrome-Profile3': r'C:\Users\sakiko\AppData\Local\Google\Chrome\User Data\Profile 3',
    'Edge-Default': r'C:\Users\sakiko\AppData\Local\Microsoft\Edge\User Data\Default',
    'QQ-Default': r'C:\Users\sakiko\AppData\Local\Tencent\QQBrowser\User Data\Default',
}

for name, root in roots.items():
    db = os.path.join(root, 'Network', 'Cookies')
    if not os.path.exists(db):
        db = os.path.join(root, 'Cookies')
    if not os.path.exists(db):
        print(f'{name}: no cookies db')
        continue
    try:
        con = sqlite3.connect(f'file:{db}?mode=ro&immutable=1', uri=True)
        cur = con.cursor()
        rows = cur.execute(
            "SELECT host_key, name FROM cookies WHERE host_key LIKE '%luogu%' OR host_key LIKE '%leetcode%' ORDER BY host_key"
        ).fetchall()
        print(f'{name}: cookies db OK, {len(rows)} luogu/leetcode rows')
        hosts = sorted(set(hk for hk, _ in rows))
        for hk in hosts:
            print(f'   host={hk}')
        con.close()
    except Exception as e:
        print(f'{name}: ERROR {e}')
