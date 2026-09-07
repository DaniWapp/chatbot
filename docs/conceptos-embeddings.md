# Conceptos: cómo una frase se convierte en un vector (embeddings)

Complemento de [conceptos-chunks-y-faiss.md](conceptos-chunks-y-faiss.md),
que trata al embedding como una caja cerrada ("cada chunk se convierte en
~384 números"). Este documento abre esa caja: qué pasa exactamente entre
que llega un texto y que sale un vector de 384 números, con ejemplos
reales generados corriendo el modelo del proyecto
(`paraphrase-multilingual-MiniLM-L12-v2`, ver `app/rag/embeddings.py`)
sobre la frase `"¿Cuándo abren las inscripciones?"`. Todos los números de
este documento son reales, no ilustrativos.

## El vocabulario de tokens: quién lo define y cómo

El modelo no lee palabras completas -- tiene un **vocabulario fijo de
250,002 fragmentos de subpalabra**, generado una sola vez durante el
entrenamiento del modelo base (antes de que este proyecto existiera), y
nunca cambia en tiempo de ejecución. No es algo que este proyecto elija,
calcule o pueda configurar.

Verificado sobre el tokenizador real:

- Clase: `PreTrainedTokenizerFast`, motor interno `Unigram` (el algoritmo
  de SentencePiece).
- Tamaño del vocabulario: 250,002 piezas.
- Tokens especiales: `<s>`, `</s>`, `<unk>`, `<pad>`, `<mask>`.

Ese vocabulario se construyó corriendo el algoritmo *Unigram* sobre un
corpus gigante de texto en ~100 idiomas: busca el conjunto de fragmentos
que mejor represente el lenguaje real. Palabras muy comunes quedan enteras
en una sola pieza; palabras raras se parten en pedazos más chicos; y en el
peor caso, hasta casi carácter por carácter -- así nunca existe una
palabra "imposible de tokenizar". Ejemplos reales:

| Palabra | Tokens reales | Por qué |
|---|---|---|
| `universidad` | `▁univers`, `idad` | palabra común → solo 2 piezas grandes |
| `inscripciones` | `▁in`, `scrip`, `ciones` | menos común → 3 piezas medianas |
| `Nubecol` | `▁Nu`, `be`, `col` | nombre propio, no está completo en el vocabulario |
| `xyzqwerty123` | `▁x`, `yz`, `q`, `wert`, `y`, `123` | secuencia inventada, nunca vista en el entrenamiento → cae hasta fragmentos casi de una letra |

## Paso 1 -- Tokenización de la frase

Aplicando ese vocabulario fijo a `"¿Cuándo abren las inscripciones?"`, el
resultado real es:

```
<s>  ▁¿  Cu  á  ndo  ▁a  bren  ▁las  ▁in  scrip  ciones  ?  </s>
```

13 tokens en total. `▁` marca el inicio de una palabra nueva (por eso
`▁a` y `bren` son piezas separadas de "abren", y `scrip`/`ciones` lo son
de "inscripciones" junto con `▁in`). `<s>` y `</s>` son marcadores de
inicio/fin que el modelo agrega siempre, no vienen del texto.

## Paso 2 -- Contextualización (12 capas de atención)

Cada uno de los 13 tokens arranca como un vector de 384 números fijo (su
significado "de diccionario", sin contexto). Luego pasa por **12 capas de
self-attention**: en cada capa, cada token "mira" a los demás tokens de la
frase y ajusta su propio vector mezclando información de los que le son
relevantes. Así, el token `▁a` (de "abren") termina con un vector distinto
en esta frase que en "abren una cuenta", porque a su alrededor tiene
"inscripciones" y no "cuenta".

Esta parte no se despliega número por número en este documento: son 12
capas × múltiples matrices de pesos aprendidos durante el entrenamiento,
miles de operaciones por token. Lo que sí es real y verificable es la
**entrada** (los 13 tokens) y la **salida** (13 vectores de 384 números,
ya contextualizados). Un vistazo real a esa salida, para dos tokens
vecinos que son parte de la misma palabra ("Cuándo" = `Cu` + `á` + `ndo`):

| dimensión | `Cu` | `á` |
|---|---|---|
| 0 | 0.0372 | 0.1019 |
| 1 | 0.4700 | 0.4167 |
| 2 | -0.3113 | -0.2731 |
| 3 | -0.3337 | -0.3066 |
| 4 | -0.1727 | -0.1627 |
| 5 | 0.0312 | 0.0259 |
| 6 | -0.4688 | -0.4435 |
| 7 | -0.1794 | -0.1454 |

Nótese lo parecidos que son, dimensión por dimensión: al ser pedazos de la
misma palabra, la atención los deja casi alineados. Sus magnitudes reales
son 6.51 (`Cu`) y 5.97 (`á`), y su producto punto sin normalizar es 38.65
-- un número que no dice nada por sí solo, porque antes de normalizar ni
las magnitudes ni los productos punto están acotados a [-1, 1]. Por eso
hace falta el paso 4.

## Paso 3 -- Mean pooling: de 13 vectores a 1 solo

Ahora hay 13 vectores de 384 números (uno por token) y se necesita **uno
solo** para representar toda la frase.
`paraphrase-multilingual-MiniLM-L12-v2` usa *mean pooling*: para cada una
de las 384 dimensiones, promedia esa dimensión a través de los 13 tokens.
Aritmética real y completa para la dimensión 0 (las otras 383 se calculan
exactamente igual, en paralelo):

| token | valor en dim 0 |
|---|---|
| `<s>` | 0.3423 |
| `▁¿` | 0.2428 |
| `Cu` | 0.0372 |
| `á` | 0.1019 |
| `ndo` | 0.0732 |
| `▁a` | 0.1803 |
| `bren` | 0.1174 |
| `▁las` | 0.0463 |
| `▁in` | 0.2051 |
| `scrip` | 0.4122 |
| `ciones` | 0.1744 |
| `?` | 0.3073 |
| `</s>` | 0.3421 |
| **suma de los 13** | **2.5824** |
| **÷ 13 = promedio (dim 0 del vector de la frase)** | **0.1986** |

Esto se repite, dimensión por dimensión, 384 veces -- el resultado es un
único vector de 384 números que representa a toda la frase.

## Paso 4 -- Normalización: la longitud se ajusta a exactamente 1

El vector promediado del paso 3 tiene una longitud (magnitud) cualquiera.
Se divide cada una de sus 384 coordenadas entre esa longitud, para que el
vector final siempre mida exactamente 1 -- esto es lo que permite que el
producto punto entre dos vectores sea directamente la similitud coseno
(ver [conceptos-chunks-y-faiss.md](conceptos-chunks-y-faiss.md)).

**¿De dónde sale la longitud?** Es el teorema de Pitágoras extendido a 384
dimensiones: se eleva al cuadrado cada coordenada del vector del paso 3,
se suman los 384 cuadrados, y se saca raíz cuadrada del total. Aritmética
real para las primeras 5 dimensiones:

| dimensión | valor (paso 3) | valor² |
|---|---|---|
| 0 | 0.1986 | 0.0395 |
| 1 | 0.1579 | 0.0249 |
| 2 | -0.2664 | 0.0710 |
| 3 | -0.1290 | 0.0166 |
| 4 | -0.2143 | 0.0459 |
| + las otras 379 dimensiones | | + 20.088 |
| **suma de los 384 cuadrados** | | **20.2921** |
| **√20.2921 = longitud del vector** | | **4.5047** |

Un cuadrado siempre es positivo (por eso la dimensión negativa -0.2664
igual suma 0.0710) -- es justamente lo que hace que esto sea una
"distancia" en línea recta y no una simple suma de coordenadas.

Aplicando esa longitud a la dimensión 0: `0.1986 ÷ 4.5047 = 0.0441`. Este
es exactamente el vector real que produce
`app/rag/embeddings.py::embed_query()` en producción para esta frase.

## ¿Por qué 384 números, y no otro tamaño?

No es una decisión de este proyecto -- viene fija en la arquitectura del
modelo descargado. Configuración real, leída del modelo cargado:

| Propiedad | Valor real |
|---|---|
| `hidden_size` | 384 |
| capas (L) | 12 |
| cabezas de atención | 12 |
| parámetros totales | 117.6M |

El nombre del modelo lo explica: **MiniLM-L12-H384**. `L12` = 12 capas de
profundidad (la misma que BERT-base). `H384` = cada vector interno mide
384 números -- exactamente la **mitad** de los 768 de BERT-base.

| Modelo | Capas | Ancho del vector | Uso típico |
|---|---|---|---|
| BERT-base | 12 | 768 | modelo "completo" de referencia |
| MiniLM-L12-H384 (este) | 12 | 384 | mismo razonamiento, mitad de ancho |

Es una decisión deliberada de quienes entrenaron el modelo (destilado
desde XLM-RoBERTa): mantener la misma profundidad de razonamiento (12
capas) pero reducir a la mitad el ancho de cada vector -- la mitad de
números que multiplicar, guardar y comparar en cada búsqueda, a cambio de
algo de matiz semántico. Para similitud de oraciones (lo que necesita este
chatbot), esa pérdida es aceptable; la ganancia en velocidad y tamaño,
corriendo local y gratis sin GPU, no lo es.

Dato que lo pone en perspectiva: de los 117.6M de parámetros totales, unos
**96M** son solo la tabla de vocabulario (250,037 piezas × 384 números) --
necesaria para cubrir ~100 idiomas. La mayor parte del "peso" del modelo
es vocabulario multilingüe, no las 12 capas de razonamiento en sí.

## El producto punto en la práctica: dos ejemplos reales

Con el vector de la pregunta ya calculado (pasos 1-4), compararlo contra
un chunk es solo multiplicar coordenada por coordenada y sumar los 384
resultados (ver [conceptos-chunks-y-faiss.md](conceptos-chunks-y-faiss.md)
para el porqué de esa operación). Dos ejemplos reales, con la misma
pregunta:

**Ejemplo A -- chunk relacionado:**

> Pregunta: "¿Cuándo abren las inscripciones?"
> Chunk: "Las inscripciones inician el 15 de enero de 2027."
> **Producto punto real: 0.7076**

**Ejemplo B -- chunk sin relación:**

> Pregunta: "¿Cuándo abren las inscripciones?"
> Chunk: "El auditorio principal tiene capacidad para 300 personas."
> **Producto punto real: 0.0898**

Con `TOP_K = 4` y 20 candidatos por pregunta (`RERANK_CANDIDATE_K`), el
chunk de "inscripciones" gana un lugar en el contexto que se le envía al
modelo; el del auditorio, con 0.09, casi nunca llega tan lejos. Dicho
así es una simplificación -- el mecanismo real, con el filtro de
relevancia movido al re-ranking y una segunda vía de búsqueda léxica,
está en
[conceptos-chunks-y-faiss.md](conceptos-chunks-y-faiss.md#cómo-se-usan-los-chunks-al-responder-una-pregunta)
y en [busqueda-lexica-bm25.md](busqueda-lexica-bm25.md).
