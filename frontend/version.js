/* Fuente de verdad de versión del frontend.
   Sincronizar con /VERSION vía: python tools/bump_version.py [--patch|--minor|--major] */
window.SUPERCLABE_VERSION = {
  version: "1.2.2",
  build: "2026.08.19",
  name: "Súper CLABE",
  label: function () {
    return "v" + this.version;
  },
  poweredLine: function () {
    return "Powered by Spotynet · " + this.label();
  },
};
