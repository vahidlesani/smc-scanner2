"""r38 — the owner-brand round (Viva 09-26).

His asks, verbatim:
  «در جاهای مورد نیاز و صفحه اول اپ لوگو خودم باید باشه»
  «در منو بخش معرفی رو اضافه کن»
  «در مورد خودم هم انگلیسی هم فارسی» — وحید لسانی / ویوا، اقتصاد کلان +
  اقتصاد سیاسی، مدیریت بانکی دانشگاه شاهرود، فعال از ۱۳۹۶، اونر VIVA-MON.labs
  «مالکیت معنوی نشان تجاری و اپلیکیشن و گیتهاب رو توش بیار با یک متن رسمی»
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return open(os.path.join(REPO, "webapp_viva.py"), encoding="utf-8").read()


def test_real_brand_logo_served_and_used():
    src = _src()
    assert '"brand-logo.png"' in src                      # safe-listed route
    assert "assets/vivasignals-logo.png" in src           # the OWNER's real file
    assert os.path.isfile(os.path.join(REPO, "assets", "vivasignals-logo.png"))
    # the placeholder emoji is gone from the shell header
    assert '<div class="logo">🎯</div>' not in src
    assert src.count("/app/icons/brand-logo.png") >= 3    # header + hero + about


def test_header_brand_is_the_owner():
    src = _src()
    assert "VIVA-MON.labs" in src
    assert "<b>VIVA-MON.labs</b>" in src
    # home hero carries the identity block
    assert 'class="hero"' in src and "Macro &amp; Political-Economy Strategy" in src


def test_about_tab_and_page_exist():
    src = _src()
    assert 'data-t="about"' in src and 'id="pg-about"' in src
    assert "repeat(6,1fr)" in src                         # 6-tab nav


def test_about_bilingual_owner_bio():
    src = _src()
    assert "وحید لساتی" in src
    assert "کارشناس و تحلیلگر اقتصاد کلان" in src
    assert "مدیریت بانکی از دانشگاه شاهرود" in src
    assert "۱۳۹۶" in src and "ویوا" in src
    assert "Vahid Lesani" in src and "Shahroud University" in src
    assert "since 2017" in src                            # 1396 ≈ 2017 EN mirror


def test_about_project_and_formal_ip_notice():
    src = _src()
    # project blurb (EN) + repo note
    assert "private research &amp; signal engine" in src
    assert "GitHub repository (private)" in src
    # formal bilingual IP / trademark notice
    assert "مالکیت معنوی" in src and "انحصاراً متعلق" in src
    assert "Intellectual Property" in src and "exclusive property" in src
    assert "without the owner's written consent" in src
    assert "© 2026 VIVA-MON.labs" in src


def test_logo_route_serves_the_brand_bytes():
    os.environ["VIVA_APP_PASSWORD"] = "test-pass-123"
    import webapp_viva
    from flask import Flask
    app = Flask(__name__)
    webapp_viva.install_viva_app(app)
    app.config["TESTING"] = True
    client = app.test_client()
    r = client.get("/app/icons/brand-logo.png")
    assert r.status_code == 200
    assert r.data[:8] == b"\x89PNG\r\n\x1a\n"              # real PNG magic
    assert len(r.data) > 20_000                            # the real art, not a stub
