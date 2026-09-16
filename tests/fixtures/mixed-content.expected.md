# Mixed content

> - [guide][manual] and `[guide](./untouched.md)`.
>
>   1. [![logo](https://raw.example/repo/ref/assets/logo.svg#mark)](https://ui.example/repo/ref/docs/guide.md#intro)
>   2. [<img src="https://raw.example/repo/ref/assets/shot.avif" height="128">](https://ui.example/repo/ref/docs/guide.md?plain=1#shot)
>
>      ```markdown
>      [example](./untouched.md)
>      ![example](./untouched.svg)
>      ```
>
>   [manual]: <https://ui.example/repo/ref/docs/guide.md#intro> "Guide"

| Resource | Example |
| --- | --- |
| [guide][manual] | `[guide](./untouched.md)` |
| ![brand][logo] | <a href="https://ui.example/repo/ref/docs/guide.md#html">HTML</a> |

<!-- [comment](./untouched.md) <img src="./untouched.svg"> -->

- Parent

  > [wrapped
  > label](https://ui.example/repo/ref/docs/a%28b%29.md "Wrapped") and [local](#mixed-content).

[logo]: https://raw.example/repo/ref/assets/logo.svg#mark

<https://example.org/docs> and <docs@example.org>.
