/**
 * 图片压缩工具（图片题目识别方案 B）
 * 选图 → canvas 压缩 → 纯 base64（不含 data: 前缀，后端自行拼 data:image/jpeg;base64,）
 */

/** 压缩图片：长边不超过 maxEdge、JPEG quality，返回纯 base64 字符串 */
export function compressImage(file: File, maxEdge = 1280, quality = 0.8): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        const scale = Math.min(1, maxEdge / Math.max(img.width, img.height));
        const w = Math.round(img.width * scale);
        const h = Math.round(img.height * scale);
        const canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext("2d");
        if (!ctx) return reject(new Error("canvas 不可用"));
        ctx.drawImage(img, 0, 0, w, h);
        resolve(canvas.toDataURL("image/jpeg", quality).split(",")[1]);
      };
      img.onerror = () => reject(new Error("图片加载失败"));
      img.src = reader.result as string;
    };
    reader.onerror = () => reject(new Error("文件读取失败"));
    reader.readAsDataURL(file);
  });
}
