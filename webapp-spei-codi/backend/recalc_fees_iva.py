"""Recalcula calculated_fee de todas las transacciones con comisión 0.05% + I.V.A. 16%.

También ajusta el saldo de membresía del payee por la diferencia (nuevo − anterior),
para que el consumo mostrado coincida con lo debitado.

Uso:
    DATABASE_URL=... python recalc_fees_iva.py          # aplica
    DATABASE_URL=... python recalc_fees_iva.py --dry-run # sólo reporta
"""
import sys
from collections import defaultdict

from app.database import SessionLocal
from app.fees import calc_membership_fee, money2
from app.models import Membership, Transaction, User


def main():
    dry = "--dry-run" in sys.argv
    db = SessionLocal()
    try:
        txs = db.query(Transaction).order_by(Transaction.settled_at.asc().nullsfirst()).all()
        print(f"{'[DRY-RUN] ' if dry else ''}Transacciones: {len(txs)}")

        deltas = defaultdict(float)
        updated = 0
        for t in txs:
            fees = calc_membership_fee(float(t.amount))
            old = float(t.calculated_fee or 0)
            new = fees["total_fee"]
            delta = money2(new - old)
            print(
                f"  {t.folio_codi}  amount={float(t.amount):.2f}  "
                f"old={old:.2f} → base={fees['base_fee']:.2f} + iva={fees['iva']:.2f} "
                f"= {new:.2f}  (Δ {delta:+.2f})"
            )
            if abs(delta) < 0.005 and abs(old - new) < 1e-9:
                continue
            if abs(old - new) < 1e-9:
                continue
            updated += 1
            deltas[str(t.payee_id)] += delta
            if not dry:
                t.calculated_fee = new

        print(f"\nFees a actualizar: {updated}/{len(txs)}")
        print("Ajuste de membresías (payee + redondeo a 2 centavos):")
        touched = set(deltas.keys())
        all_ms = db.query(Membership).all()
        for m in all_ms:
            uid = str(m.user_id)
            u = db.query(User).filter(User.id == m.user_id).first()
            alias = u.alias if u else uid
            delta = money2(deltas.get(uid, 0))
            prev = float(m.balance)
            nxt = money2(prev - delta)
            status_note = ""
            if nxt <= 0:
                nxt = 0.0
                status_note = " → blocked"
            elif m.status == "blocked" and nxt > 0:
                status_note = " → active"
            if abs(prev - nxt) < 1e-9 and uid not in touched:
                continue
            print(f"  {alias}: balance {prev:.2f} → {nxt:.2f} (Δ fee {delta:+.2f}){status_note}")
            if not dry:
                m.balance = nxt
                if nxt <= 0:
                    m.status = "blocked"
                elif m.status == "blocked" and nxt > 0:
                    m.status = "active"

        if dry:
            print("\n(--dry-run) No se aplicó ningún cambio.")
            db.rollback()
        else:
            db.commit()
            print("\n✓ Recálculo aplicado (fee + I.V.A. a 2 centavos) y saldos ajustados.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
