// XGEN CREATOR 콘솔 게이트웨이 라우트 — apps/web/src/app/creator/page.tsx 로 복사
// NEXT_PUBLIC_CREATOR_URL: creator web 콘솔 주소 (예: http://localhost:8990)
"use client";

export default function CreatorGatewayPage() {
  const url = process.env.NEXT_PUBLIC_CREATOR_URL || "http://localhost:8990";
  return (
    <iframe
      src={url}
      title="XGEN CREATOR 콘솔"
      style={{ width: "100%", height: "calc(100vh - 64px)", border: 0 }}
    />
  );
}
