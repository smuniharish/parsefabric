# Tokenizers

`measure_compression` reports savings in tokens as well as bytes, because
aggregates often feed a language model. The default `ApproximateTokenizer`
counts one token per four UTF-8 bytes. Count with your model's own tokenizer
for exact figures.

Subclass `Tokenizer` and implement `async count(text)`, which returns the
number of tokens in `text`. `count_bytes(data)` decodes bytes as UTF-8, with
replacement characters, before calling `count`; override it when your
tokenizer works on raw bytes. Offload slow tokenizers with
`asyncio.to_thread`.

A tokenizer that counts words and punctuation marks:

```python
import asyncio
import re

from parsefabric import ParseEngine, measure_compression
from parsefabric.builtins import ApplicationLogParser
from parsefabric.compression import Tokenizer
from parsefabric.testing import check_tokenizer

TOKEN = re.compile(r"\w+|[^\w\s]")


class WordTokenizer(Tokenizer):
    """Count words and punctuation marks."""

    async def count(self, text: str) -> int:
        return len(TOKEN.findall(text))


async def main() -> None:
    await check_tokenizer(WordTokenizer())
    source = "payment gateway timed out after 30 seconds, retry scheduled\n" * 100
    engine = ParseEngine()
    parser = ApplicationLogParser()
    result = await engine.parse(parser, source)
    stored = await engine.serialize(await engine.aggregate(parser, result.events))
    metrics = await measure_compression(source, stored, tokenizer=WordTokenizer())
    print(metrics.input_tokens, metrics.output_tokens < metrics.input_tokens)


asyncio.run(main())
```

```text
1000 True
```

`check_tokenizer(tokenizer, samples)` checks that empty text counts zero
tokens, that counts are integers that never shrink as text is appended, and
that `count_bytes` agrees with `count` for UTF-8 text.

To count with tiktoken, for example, return
`len(encoding.encode(text))` from `count`, creating the encoding once in
`__init__`.
