# tools/

`npm install` が使えない端末向けの、ビルド不要の動作確認手段。**`npm run dev` が動くなら、常にそちらを優先する**(こちらはVite無しの簡易版で、初回描画が遅くHMRも無い)。

## devserver.py

`npm run dev` の代わりにリポジトリを直接配信する。`three` は CDN(jsdelivr)の import map で解決し、ビルドステップ無しでアプリが動く。

```
python tools/devserver.py            # http://127.0.0.1:5188/ で待受
python tools/devserver.py --port 6000
```

## screenshot.py

ヘッドレスChrome/Edgeでページを開き、`window.__enoden.ready` を待って(任意の)JSを実行し、スクリーンショットとコンソールエラーを取得する。`devserver.py` が起動していなければ自動で起動する。

```
pip install websocket-client   # 初回のみ

# 起動確認だけ
python tools/screenshot.py --path "/?q=low" --out out.png

# 任意のJSを実行してから撮影(window.__enoden 経由でシミュレーションを進める等)
python tools/screenshot.py --path "/?q=high" --eval snippet.js --out out.png --settle-ms 3000
```

`--eval` に渡すJSの中では `window.__enoden` が使える(`src/main.js` 末尾の debug ハンドル参照)。主なもの:

- `window.__enoden.ready` — 読み込み完了フラグ
- `window.__enoden.start()` — タイトル画面の「散歩をはじめる」を押す
- `window.__enoden.goto(x, z, yaw)` / `setCam(yaw, pitch, dist)` — 瞬間移動・カメラ固定
- `window.__enoden.setTime('day'|'dusk'|'night')`
- `window.__enoden.applyQuality('low'|'medium'|'high')`
- `window.__enoden.sim(dt, cmd)` — 描画せずに1フレーム分シミュレーションだけ進める(`cmd = {x,y,run,sprint}`)。ロジックを高速に検証したい時用
- `window.__enoden.player` / `.train` / `.ground` / `.scene` / `.camera` / `.renderer` / `.tod` — 各オブジェクトへの参照

例(`snippet.js`):

```js
window.__enoden.start();
await new Promise(r => setTimeout(r, 300));
window.__enoden.setTime('dusk');
window.__enoden.goto(-32.5, -2.6, Math.PI / 2);
window.__enoden.setCam(2.0, 0.25, 5);
await new Promise(r => setTimeout(r, 3000));
```

## 既知の制約

- Windows の `socketserver` は、Chromeがコネクションを先に切ると `ConnectionAbortedError` をコンソールに吐くことがあるが無害(リクエスト自体は完了している)。
- Vercelのプレビューデプロイ(PRごとに作られるURL)はSSO保護がかかっており、このツールやCDP経由ではアクセスできない。実機確認はこのローカルツールか、ユーザーに実URLを開いてもらう形になる。
