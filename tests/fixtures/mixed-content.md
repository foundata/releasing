# Mixed content

> - [guide][manual] and `[guide](./untouched.md)`.
>
>   1. [![logo](./assets/logo.svg#mark)](./docs/guide.md#intro)
>   2. [<img src="./assets/shot.avif" height="128">](./docs/guide.md?plain=1#shot)
>
>      ```markdown
>      [example](./untouched.md)
>      ![example](./untouched.svg)
>      ```
>
>   [manual]: <./docs/guide.md#intro> "Guide"

| Resource | Example |
| --- | --- |
| [guide][manual] | `[guide](./untouched.md)` |
| ![brand][logo] | <a href="./docs/guide.md#html">HTML</a> |

<!-- [comment](./untouched.md) <img src="./untouched.svg"> -->

- Parent

  > [wrapped
  > label](./docs/a(b).md "Wrapped") and [local](#mixed-content).

[logo]: ./assets/logo.svg#mark

<https://example.org/docs> and <docs@example.org>.
