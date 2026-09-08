"""
Comando de management para reactivar un StockBalde que fue desactivado
incorrectamente por _corregir_baldes_incorrectamente_activos().

Uso:
    python manage.py reactivar_balde --balde-id 6437 --dry-run
    python manage.py reactivar_balde --balde-id 6437

El modo --dry-run imprime el informe sin modificar la base de datos.
Sin --dry-run, crea un backup y aplica el cambio atómicamente.

Restricciones (CLAUDE.md):
  - Nunca modificar db.sqlite3 directamente.
  - Toda migración de datos debe tener modo --dry-run y generar un informe.
  - No crear ingresos nuevos ni eliminar movimientos existentes.
"""
import os
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from app_inventario.models import StockBalde, RegistroMovimiento
from app_inventario.utils.backups import make_startup_backup


class Command(BaseCommand):
    help = "Reactiva un StockBalde desactivado incorrectamente (is_activo=True, fecha_retiro=None)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--balde-id",
            type=int,
            required=True,
            help="ID del StockBalde a reactivar.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Muestra el informe sin modificar la base de datos.",
        )

    def handle(self, *args, **options):
        balde_id = options["balde_id"]
        dry_run = options["dry_run"]

        # ── Buscar el balde ───────────────────────────────────────────────────
        try:
            balde = StockBalde.objects.select_related("producto").get(pk=balde_id)
        except StockBalde.DoesNotExist:
            raise CommandError(f"StockBalde con ID {balde_id} no existe.")

        # ── Movimientos asociados ─────────────────────────────────────────────
        movimientos = list(
            RegistroMovimiento.objects
            .filter(balde=balde)
            .order_by("timestamp")
            .values("id", "tipo", "timestamp", "codigo_barras")
        )
        ultimo_rm = (
            RegistroMovimiento.objects
            .filter(codigo_barras=balde.codigo_barras)
            .order_by("-timestamp", "-id")
            .values("id", "tipo", "timestamp")
            .first()
        )

        # ── Informe ───────────────────────────────────────────────────────────
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("═" * 60))
        self.stdout.write(self.style.MIGRATE_HEADING("  INFORME DE REACTIVACIÓN DE BALDE"))
        if dry_run:
            self.stdout.write(self.style.WARNING("  [MODO DRY-RUN — sin cambios en la base de datos]"))
        self.stdout.write(self.style.MIGRATE_HEADING("═" * 60))
        self.stdout.write(f"  ID            : {balde.pk}")
        self.stdout.write(f"  Producto      : {balde.producto.nombre} (PLU {balde.producto.plu})")
        self.stdout.write(f"  Código barras : {balde.codigo_barras}")
        self.stdout.write(f"  Peso          : {balde.peso} kg")
        self.stdout.write(f"  is_activo     : {balde.is_activo}  →  True")
        self.stdout.write(f"  fecha_retiro  : {balde.fecha_retiro}  →  None")
        self.stdout.write(f"  timestamp     : {balde.timestamp}")
        self.stdout.write("")
        self.stdout.write(f"  Movimientos asociados al balde (balde_id={balde.pk}):")
        if movimientos:
            for m in movimientos:
                self.stdout.write(f"    RM #{m['id']}  tipo={m['tipo']}  ts={m['timestamp']}")
        else:
            self.stdout.write("    (ninguno con referencia directa al balde)")
        self.stdout.write("")
        if ultimo_rm:
            self.stdout.write(
                f"  Último RM con mismo codigo_barras: "
                f"#{ultimo_rm['id']} tipo={ultimo_rm['tipo']} ts={ultimo_rm['timestamp']}"
            )
        self.stdout.write(self.style.MIGRATE_HEADING("═" * 60))
        self.stdout.write("")

        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry-run completado. No se realizaron cambios."))
            return

        # ── Validación preventiva ─────────────────────────────────────────────
        if balde.is_activo:
            self.stdout.write(self.style.WARNING(
                f"El balde {balde_id} ya está activo (is_activo=True). No se requiere cambio."
            ))
            return

        # ── Backup ────────────────────────────────────────────────────────────
        self.stdout.write("Creando backup de la base de datos...")
        backup_path = make_startup_backup(keep_last=20)
        if backup_path:
            self.stdout.write(self.style.SUCCESS(f"Backup creado: {backup_path}"))
        else:
            raise CommandError("No se pudo crear el backup. Abortando sin modificar datos.")

        # ── Aplicar cambio ────────────────────────────────────────────────────
        with transaction.atomic():
            balde.is_activo = True
            balde.fecha_retiro = None
            balde.save(update_fields=["is_activo", "fecha_retiro"])

        balde.refresh_from_db()
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"StockBalde {balde_id} reactivado correctamente."
        ))
        self.stdout.write(f"  is_activo    : {balde.is_activo}")
        self.stdout.write(f"  fecha_retiro : {balde.fecha_retiro}")
        self.stdout.write("")
