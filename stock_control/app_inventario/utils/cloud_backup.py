import os
import gzip
import shutil
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class CloudBackupManager:
    """
    Gestor centralizado de backups en la nube.
    Soporta múltiples proveedores y maneja rotación automática.
    """
    
    def __init__(self):
        self.provider = self._get_provider()
        self.max_backups = getattr(settings, 'CLOUD_BACKUP_KEEP', 30)
        
    def _get_provider(self):
        """Carga el proveedor configurado en settings.py"""
        provider_name = getattr(settings, 'CLOUD_BACKUP_PROVIDER', 'google_drive')
        
        if provider_name == 'google_drive':
            from .cloud_providers.google_drive import GoogleDriveProvider
            return GoogleDriveProvider()
        elif provider_name == 'dropbox':
            from .cloud_providers.dropbox_provider import DropboxProvider
            return DropboxProvider()
        elif provider_name == 'onedrive':
            from .cloud_providers.onedrive_provider import OneDriveProvider
            return OneDriveProvider()
        else:
            raise ValueError(f"Proveedor no soportado: {provider_name}")
    
    def backup_now(self, compress: bool = True) -> Dict[str, any]:
        """
        Realiza un backup inmediato y lo sube a la nube.
        
        Returns:
            dict con 'success', 'filename', 'size', 'cloud_id', etc.
        """
        try:
            # 1. Crear backup local comprimido
            backup_file = self._create_local_backup(compress)
            
            # 2. Subir a la nube
            cloud_id = self.provider.upload(backup_file)
            
            # 3. Limpiar backups viejos
            self._cleanup_old_backups()
            
            # 4. Borrar archivo local (opcional, según config)
            if getattr(settings, 'CLOUD_BACKUP_DELETE_LOCAL', True):
                os.remove(backup_file)
            
            file_size = Path(backup_file).stat().st_size if Path(backup_file).exists() else 0
            
            logger.info(f"✅ Backup subido a la nube: {cloud_id}")
            
            return {
                'success': True,
                'filename': Path(backup_file).name,
                'size': file_size,
                'cloud_id': cloud_id,
                'provider': self.provider.name,
                'timestamp': datetime.now().isoformat(),
            }
            
        except Exception as e:
            logger.error(f"❌ Error en backup a la nube: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat(),
            }
    
    def _create_local_backup(self, compress: bool) -> Path:
        """Crea una copia temporal de la BD (con o sin compresión)."""
        from django.db import connection
        
        # Obtener ruta de la BD actual
        db_path = Path(connection.settings_dict['NAME'])
        
        # Crear carpeta temporal para backups
        backup_dir = Path(settings.BASE_DIR) / 'temp_backups'
        backup_dir.mkdir(exist_ok=True)
        
        # Nombre del archivo
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        if compress:
            backup_file = backup_dir / f"backup_{timestamp}.db.gz"
            
            # Comprimir directamente
            with open(db_path, 'rb') as f_in:
                with gzip.open(backup_file, 'wb', compresslevel=6) as f_out:
                    shutil.copyfileobj(f_in, f_out)
        else:
            backup_file = backup_dir / f"backup_{timestamp}.db"
            shutil.copy2(db_path, backup_file)
        
        logger.info(f"📦 Backup local creado: {backup_file} ({backup_file.stat().st_size / 1024:.1f} KB)")
        return backup_file
    
    def _cleanup_old_backups(self):
        """Elimina backups viejos en la nube, manteniendo solo los últimos N."""
        try:
            all_backups = self.provider.list_backups()
            
            # Ordenar por fecha (más reciente primero)
            all_backups.sort(key=lambda x: x['modified'], reverse=True)
            
            # Eliminar los que exceden el límite
            to_delete = all_backups[self.max_backups:]
            
            for backup in to_delete:
                self.provider.delete(backup['id'])
                logger.info(f"🗑️  Backup eliminado de la nube: {backup['name']}")
        
        except Exception as e:
            logger.warning(f"⚠️  No se pudo limpiar backups viejos: {e}")
    
    def restore_from_cloud(self, cloud_id: str) -> bool:
        """
        Restaura la BD desde un backup en la nube.
        
        Args:
            cloud_id: ID del archivo en la nube
        
        Returns:
            True si se restauró exitosamente
        """
        try:
            from django.db import connection
            
            # 1. Descargar de la nube
            download_path = self.provider.download(cloud_id)
            
            # 2. Descomprimir si es necesario
            if download_path.suffix == '.gz':
                db_file = download_path.with_suffix('')
                with gzip.open(download_path, 'rb') as f_in:
                    with open(db_file, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                os.remove(download_path)  # borrar el .gz
            else:
                db_file = download_path
            
            # 3. Cerrar conexión actual
            connection.close()
            
            # 4. Hacer backup de seguridad de la BD actual
            db_path = Path(connection.settings_dict['NAME'])
            backup_seguridad = db_path.with_suffix('.db.before_restore')
            shutil.copy2(db_path, backup_seguridad)
            
            # 5. Reemplazar BD
            shutil.copy2(db_file, db_path)
            
            # 6. Limpiar archivos temporales
            os.remove(db_file)
            
            logger.info(f"✅ BD restaurada desde la nube: {cloud_id}")
            logger.info(f"💾 Backup de seguridad guardado en: {backup_seguridad}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error al restaurar desde la nube: {e}", exc_info=True)
            return False
    
    def list_cloud_backups(self) -> List[Dict]:
        """Lista todos los backups disponibles en la nube."""
        try:
            backups = self.provider.list_backups()
            backups.sort(key=lambda x: x['modified'], reverse=True)
            return backups
        except Exception as e:
            logger.error(f"❌ Error listando backups: {e}")
            return []
    
    def get_status(self) -> Dict:
        """Estado del sistema de backups."""
        try:
            backups = self.list_cloud_backups()
            total_size = sum(b.get('size', 0) for b in backups)
            
            last_backup = None
            if backups:
                last_backup = {
                    'name': backups[0]['name'],
                    'date': backups[0]['modified'],
                    'size': backups[0].get('size', 0),
                }
            
            return {
                'provider': self.provider.name,
                'connected': self.provider.is_connected(),
                'total_backups': len(backups),
                'total_size_mb': total_size / (1024 * 1024),
                'last_backup': last_backup,
                'max_backups': self.max_backups,
            }
        except Exception as e:
            return {
                'provider': getattr(self.provider, 'name', 'unknown'),
                'connected': False,
                'error': str(e),
            }
