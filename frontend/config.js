/* SC-DEV-SIG-v1: anoKdjky8sQPSFUizO6dsdUlocN0u8Ap7Pl1wohULe85BuQV06DmNQHSLrGB9xd6yYBrXP5VokoUSfFppohTzGq4_fxTMTbPem0dSVDFpp8Z8wkeWGF18kCn-AsSw5v9zd2uZOyLkfvf4EU_W1cfxDTd8g== */
/* firma de autoría cifrada AES-256-GCM — tools/verify_dev_signature.py */
// Configuración del frontend.
// La app se sirve desde el backend (mismo origen) y la API vive bajo /api/v1.
// Todos los datos viven en la DB del sistema, compartidos entre dispositivos.
window.SUPERCLABE_CONFIG = {
  API_BASE: "/api/v1",
  USE_API: true,
  // Versión: ver frontend/version.js (sincronizada con /VERSION)
  get APP_VERSION() {
    return (window.SUPERCLABE_VERSION && SUPERCLABE_VERSION.version) || "0.0.0";
  },
};
