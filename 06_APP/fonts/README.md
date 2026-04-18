# Fuentes para PDF

Esta carpeta contiene fuentes personalizadas para el generador de PDFs.

## Estructura

```
fonts/
├── README.md
└── (archivos de fuente .ttf, .otf, .ttc)
```

## Cómo agregar fuentes

1. Copia tus archivos de fuente (.ttf, .otf) en esta carpeta
2. El sistema los detectará automáticamente
3. Se recomienda incluir:
   - Una fuente que soporte emojis (ej: NotoColorEmoji.ttf)
   - Una fuente regular como fallback (ej: DejaVuSans.ttf)

## Fuentes recomendadas

### Para emojis:
- **Noto Color Emoji** (https://github.com/googlefonts/noto-emoji)
- **Segoe UI Emoji** (Windows, ya incluido)
- **Apple Color Emoji** (Mac)

### Fallback:
- **DejaVu Sans** (libre, multiplataforma)
- **Liberation Sans** (libre)
- **Noto Sans** (libre, Google)

## Limitaciones

- **Emojis**: Si no hay fuente de emoji, se usará Helvetica/Arial
- **Caracteres especiales**: Algunos emojis pueden no aparecer en Linux/Docker
- **Símbolos especiales**: Se mostrarán como "??" si no hay fuente compatible

## Para Docker/Linux

Si ejecutas en Docker, instala fuentes del sistema:
```dockerfile
RUN apt-get update && apt-get install -y fonts-noto-color-emoji fonts-dejavu
```
