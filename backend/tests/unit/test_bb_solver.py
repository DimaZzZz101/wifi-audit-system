"""Unit tests: app.services.bb_solver (no mocks)."""

from app.services import bb_solver
from app.services.bb_solver import APParams, EXECUTION_ORDER, _dep_feasible, ap_params_from_recon, phi, solve


def _names(result):
    return [a["name"] for a in result.selected_attacks]


def test_solve_full_budget():
    """
    Максимальный бюджет времени для типового WPA2 AP с клиентами и WPS.
    Вход: APParams (WPA2, WPS, клиенты, HT), time_budget_s=50000.
    Выход: f_star > 0, в выборке есть атаки: handshake_capture, pmkid_capture, wps_pixie, psk_crack, dos.
    """
    p = APParams(x1="WPA2", x2=1, x4=3, x9=1)
    r = solve(p, time_budget_s=50000.0)
    names = set(_names(r))
    assert r.f_star > 0
    assert "handshake_capture" in names
    assert "pmkid_capture" in names
    assert "wps_pixie" in names
    assert "psk_crack" in names
    assert "dos" in names


def test_solve_zero_budget():
    """
    Нулевой бюджет - нельзя выполнить ни одной платной по времени атаки.
    Вход: APParams (WPA2, WPS, клиенты, HT), time_budget_s=0.0.
    Выход: f_star=0.0, пустой selected_attacks.
    """
    p = APParams(x1="WPA2", x2=1, x4=3, x9=1)
    r = solve(p, time_budget_s=0.0)
    assert r.selected_attacks == []
    assert r.f_star == 0.0


def test_solve_single_attack_budget():
    """
    Узкий бюджет - не больше одной тяжёлой атаки.
    Вход: APParams (WPA2, WPS, клиенты, HT), time_budget_s=2000.0, solver_timeout_s=5.0.
    Выход: не более одной атаки в выборке selected_attacks, если есть - одна из атак: handshake_capture, wps_pixie, pmkid_capture.
    """
    p = APParams(x1="WPA2", x2=1, x4=3, x9=1)
    r = solve(p, time_budget_s=2000.0, solver_timeout_s=5.0)
    assert len(r.selected_attacks) <= 1
    if r.selected_attacks:
        assert r.selected_attacks[0]["name"] in ("handshake_capture", "wps_pixie", "pmkid_capture")


def test_solve_wps_pixie_only():
    """
    WEP + WPS: применима в основном только атака wps_pixie.
    Вход: x1=WEP, x2=1, x4=0, x9=0, time_budget_s=50000.0.
    Выход: ровно одна атака в выборке - wps_pixie.
    """
    p = APParams(x1="WEP", x2=1, x4=0, x9=0)
    r = solve(p, time_budget_s=50000.0)
    names = _names(r)
    assert len(names) == 1 and names[0] == "wps_pixie"


def test_solve_no_applicable():
    """
    Открытая сеть - нет применимых атак в модели.
    Вход: x1=OPEN, x2=0, x4=0, x9=0, time_budget_s=50000.0.
    Выход: пустой выбор selected_attacks, f_star=0.0.
    """
    p = APParams(x1="OPEN", x2=0, x4=0, x9=0)
    r = solve(p, time_budget_s=50000.0)
    assert r.selected_attacks == []
    assert r.f_star == 0.0


def _attack_index(name: str) -> int:
    for idx, row in enumerate(bb_solver.DEFAULT_ATTACKS):
        if row[0] == name:
            return idx
    raise AssertionError(name)


def test_solve_execution_order():
    """
    Порядок execution_order согласован с шаблоном EXECUTION_ORDER, psk_crack последний в выборке.
    Вход: x1=WPA2, x2=1, x4=3, x9=1, time_budget_s=50000.0.
    Выход: индексы атак в execution_order неубывают по EXECUTION_ORDER, psk_crack в конце, если есть.
    """
    p = APParams(x1="WPA2", x2=1, x4=3, x9=1)
    r = solve(p, time_budget_s=50000.0)
    positions = [_attack_index(n) for n in r.execution_order]
    exec_pos = [EXECUTION_ORDER.index(i) for i in positions]
    assert exec_pos == sorted(exec_pos)
    if "psk_crack" in r.execution_order:
        assert r.execution_order.index("psk_crack") == len(r.execution_order) - 1


def test_solve_dragonshift_transition_mode():
    """
    WPA2/WPA3 transition mode + клиенты: dragonshift может быть в решении.
    Вход: x1=WPA2/WPA3-TM, x4>0, x9=1 (HT), WPS не обязателен, time_budget_s=10000.0.
    Выход: dragonshift входит в выборку selected_attacks.
    """
    p = APParams(x1="WPA2/WPA3-TM", x2=0, x4=2, x9=1)
    r = solve(p, time_budget_s=10000.0)
    names = _names(r)
    assert "dragonshift" in names


def test_solve_dragonshift_not_for_pure_wpa2():
    """
    Чистый WPA2 без transition mode: dragonshift не применим.
    Вход: x1=WPA2 (не TM), x4>0, x9=1, без WPS, time_budget_s=10000.0.
    Выход: dragonshift отсутствует в выборке selected_attacks.
    """
    p = APParams(x1="WPA2", x2=0, x4=2, x9=1)
    r = solve(p, time_budget_s=10000.0)
    assert "dragonshift" not in _names(r)


def test_phi_recon_always_true():
    """
    Предикат phi для j=0 (recon): всегда True.
    Вход: j=0, кортеж параметров AP произвольный (для j=0 не используется).
    Выход: phi(0, ("WPA2", 0, 0, 0, 0, 0)) is True.
    """
    assert phi(0, ("WPA2", 0, 0, 0, 0, 0)) is True


def test_phi_handshake_needs_client():
    """
    phi для атаки handshake (j=1): нужны клиенты (x4 > 0) и WPA2-подобный x1.
    Вход: j=1, кортеж (x1..x9): без клиентов (x4=0) и с одним клиентом (x4=1).
    Выход: False при x4=0, True при x4=1.
    """
    assert phi(1, ("WPA2", 0, 0, 0, 0, 0)) is False
    assert phi(1, ("WPA2", 0, 0, 1, 0, 0)) is True


def test_phi_krack_always_false():
    """
    KRACK (j=6) в модели отключён (phi всегда False).
    Вход: j=6, любой валидный кортеж параметров AP.
    Выход: phi(6, ...) is False (в тесте - типичный кортеж с клиентами и HT).
    """
    assert phi(6, ("WPA2", 1, 0, 3, 0, 1)) is False


def test_ap_params_from_recon_wpa2():
    """
    Маппинг recon в APParams: display_security WPA2.
    Вход: словарь recon с security_info.display_security=WPA2, wps={}, tagged_params={}, client_count=0.
    Выход: p.x1 == "WPA2".
    """
    ap = {"security_info": {"display_security": "WPA2"}, "wps": {}, "tagged_params": {}, "client_count": 0}
    p = ap_params_from_recon(ap)
    assert p.x1 == "WPA2"


def test_ap_params_from_recon_wps_enabled():
    """
    Маппинг recon в APParams: WPS enabled -> x2=1.
    Вход: словарь recon с wps.enabled=True, tagged_params={}, client_count=0.
    Выход: p.x2 == 1.
    """
    ap = {"security_info": {}, "wps": {"enabled": True}, "tagged_params": {}, "client_count": 0}
    p = ap_params_from_recon(ap)
    assert p.x2 == 1


def test_ap_params_from_recon_pmf_required():
    """
    Маппинг recon в APParams: PMF required -> x3=2.
    Вход: словарь recon с security_info.pmf="required", wps={}, tagged_params={}, client_count=0.
    Выход: p.x3 == 2.
    """
    ap = {"security_info": {"pmf": "required"}, "wps": {}, "tagged_params": {}, "client_count": 0}
    p = ap_params_from_recon(ap)
    assert p.x3 == 2


def test_dep_feasible_conj_satisfied():
    """
    Конъюнктивная зависимость: атака 1 требует recon (0).
    Вход: assignment {0:1}, vuln_j=1.
    Выход: _dep_feasible({0: 1}, 1) == True.
    """
    assert _dep_feasible({0: 1}, 1) is True


def test_dep_feasible_conj_not_satisfied():
    """
    Та же конъюнкция (0 -> 1): без выбранного recon атака 1 недопустима.
    Вход: assignment {} (recon не взят), vuln_j=1.
    Выход: _dep_feasible({}, 1) == False.
    """
    assert _dep_feasible({}, 1) is False


def test_dep_feasible_disj_psk_crack():
    """
    Дизъюнктивная зависимость для атаки psk_crack: нужен handshake (1) или pmkid (2).
    Вход: assignment {1:1}, vuln_j=5.
    Вход: три варианта assignment для vuln_j=5.
    Выход: _dep_feasible({1: 1}, 5) == True.
    """
    assert _dep_feasible({1: 1}, 5) is True
