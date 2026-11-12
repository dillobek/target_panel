# Target Panel — targetologlar uchun hisobot va tahlil paneli

Meta Ads (va keyinchalik Telegram Ads) accountlaridan ma'lumot oladi. Har bir mijozning Telegram guruhiga
kunlik va haftalik hisobot yuboradi, sizga esa alertlar va tahlil keladi. Hammasi serverda 24/7 ishlaydi:
kompyuter yoki brauzer yoqiq bo'lishi shart emas.

## Tuzilishi

| Servis | Texnologiya | Vazifasi |
|---|---|---|
| `api` | NestJS | Adminka (sahifalar + REST API), Meta webhook (`/webhooks/meta`) |
| `worker` | Python, APScheduler | Har 15 daqiqada accountlar holati, har soatda insights, hisobotlar, alertlar, 08:30 da tahlil |
| `bot` | Python, Aiogram 3 | Guruhlarni avtomatik ro'yxatga oladi, `/hisobot`, `/id`, worker nazorati |
| `db` | PostgreSQL 16 | Barcha ma'lumotlar (tokenlar AES-256-GCM bilan shifrlangan) |

## 1. Tayyorgarlik (5 daqiqa)

1. **Bot:** @BotFather → `/newbot` → token va username'ni oling. `/setprivacy` → *Disable* (guruhda buyruqlarni ko'rishi uchun).
2. **Telegram ID:** @userinfobot'ga yozing, u ID'ingizni ko'rsatadi.
3. **Meta token:** Business Settings → Users → System users → *Add* (Admin) → *Assign assets* (15 ta account, *View performance*) →
   *Generate token*: ilovangiz, ruxsatlar `ads_read`, `read_insights`, `business_management`, muddat **Never**.

## 2. Serverga o'rnatish

Kompyuteringizda (arxiv yuklangan papkada):

```bash
scp targetpanel.zip root@13.140.128.2:/opt/
ssh root@13.140.128.2
```

Serverda:

```bash
cd /opt && apt-get install -y unzip && unzip -o targetpanel.zip && cd targetpanel
bash setup.sh
```

`setup.sh` bot tokeni, ID va adminka parolini so'raydi, qolgan maxfiy kalitlarni o'zi yaratadi va 4 ta servisni ishga tushiradi.

## 3. Adminkaga kirish

Adminka xavfsizlik uchun faqat server ichida ochiq (`127.0.0.1:3000`). Kompyuteringizda:

```bash
ssh -L 3000:localhost:3000 root@13.140.128.2
```

Brauzerda **http://localhost:3000** ni oching va parol bilan kiring.

1. **Ulanishlar** → Meta System User tokenini qo'ying → *Tekshirish va ulash*. Accountlar bir daqiqada chiqadi.
2. Botni har bir mijoz guruhiga **admin** qilib qo'shing (*Guruhga qo'shish* tugmasi). Guruh adminkada paydo bo'ladi va sizga xabar keladi.
3. **Mijozlar** → *+ Yangi mijoz* → natija turi, account va guruhni tanlang → *Saqlash* → *Sinov hisobotini yuborish*.
4. **Hisobot va alertlar** → chegaralar va "mijoz guruhiga ham" sozlamalari.

## 4. Meta webhook (real vaqt alertlari, ixtiyoriy)

Webhook uchun domen va HTTPS kerak. Domen serverga yo'naltirilgandan keyin (masalan `panel.aipixel.uz`):

```bash
apt-get install -y nginx certbot python3-certbot-nginx
cat > /etc/nginx/sites-available/targetpanel <<'EOF'
server {
  server_name panel.aipixel.uz;
  location / { proxy_pass http://127.0.0.1:3000; proxy_set_header Host $host; proxy_set_header X-Forwarded-For $remote_addr; }
}
EOF
ln -sf /etc/nginx/sites-available/targetpanel /etc/nginx/sites-enabled/ && nginx -t && systemctl reload nginx
certbot --nginx -d panel.aipixel.uz
```

Meta App → Webhooks → *Ad Account*:
- Callback URL: `https://panel.aipixel.uz/webhooks/meta`
- Verify token: `grep META_WEBHOOK_VERIFY_TOKEN /opt/targetpanel/.env`
- Fieldlar: `with_issues_ad_objects`, `in_process_ad_objects`, `creative_fatigue`, `ad_recommendations`

`META_APP_SECRET` `.env` da bo'lishi shart (imzo tekshiruvi). Har bir accountni ilovaga obuna qiling:

```bash
TOKEN='System User tokeningiz'
for ACT in $(curl -s "https://graph.facebook.com/v26.0/me/adaccounts?fields=account_id&limit=100&access_token=$TOKEN" | python3 -c "import sys,json;print(' '.join(a['account_id'] for a in json.load(sys.stdin)['data']))"); do
  curl -s -X POST "https://graph.facebook.com/v26.0/act_$ACT/subscribed_apps" -d "access_token=$TOKEN"; echo " act_$ACT"
done
```

Webhooksiz ham tizim ishlaydi: holat o'zgarishlarini har 15 daqiqada o'zi tekshiradi.

## 5. Kundalik buyruqlar

```bash
cd /opt/targetpanel
docker compose ps                      # holat
docker compose logs -f --tail 100 worker
docker compose logs -f --tail 100 bot
docker compose restart worker bot      # .env o'zgarganda
docker compose up -d --build           # yangi kod yuklangandan keyin
```

**Zaxira nusxa (har kecha 03:00, 7 kun saqlanadi):**

```bash
mkdir -p /opt/backups && (crontab -l 2>/dev/null; echo '0 3 * * * cd /opt/targetpanel && docker compose exec -T db pg_dump -U targetpanel targetpanel | gzip > /opt/backups/tp-$(date +\%F).sql.gz && find /opt/backups -name "tp-*.sql.gz" -mtime +7 -delete') | crontab -
```

## Jadval

| Vaqt | Nima bo'ladi |
|---|---|
| Har 15 daqiqa | Account holati, spend limit → alert |
| Har soat + 08:40 | Oxirgi 7 kunlik insights (atributsiya kechikishini ham qamrab oladi) |
| 08:30 | Har bir mijoz bo'yicha tahlil → sizga (AI kaliti bo'lsa, AI xulosa bilan) |
| Mijoz vaqti (standart 09:00) | Kechagi hisobot → mijoz guruhiga |
| Dushanba 10:00 | Haftalik hisobot va o'tgan hafta bilan solishtirish |
| Har daqiqa | Webhook hodisalari, adminka vazifalari |

Server o'chib qolsa, hisobot belgilangan vaqtdan keyingi 3 soat ichida baribir yuboriladi. Worker 30 daqiqa javob bermasa,
bot sizga "Worker to'xtadi" deb yozadi.

## Telegram Ads

TG Ads ulanishini adminkada saqlash mumkin (kalit shifrlanadi). Ma'lumot olish moduli (`worker/app/tgads.py`) esa kabinetdagi
API hujjati asosida qo'shiladi. Hujjatni yuborsangiz, shu modul yoziladi va TG Ads hisobotlari ham avtomatik ishlaydi.
