# Third-party notices

## coltonalmeida/twitch-clipper

Parts of Claud are adapted from https://github.com/coltonalmeida/twitch-clipper:
the clip-ranking signals and weights (`claud/ranking.py`), the content-filter term list
(`claud/content_filter.py`), the hook overlay idea and keyword fallbacks (`claud/hooks.py`),
and the TikTok drafts upload mode (`claud/uploaders/tiktok.py`).

```
MIT License

Copyright (c) 2026 Colton Almeida

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## YuNet face detection model

`claud/models/face_detection_yunet_2023mar.onnx` is the YuNet model from the OpenCV Zoo
(https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet), distributed under
the MIT License. Copied from the twitch-clipper repository; SHA-256
`8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`.
