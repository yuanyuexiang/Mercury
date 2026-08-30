"use client";
// 兼容旧链接：/conversations/{id} → 工作台 /conversations?id={id}
import { redirect, useParams } from "next/navigation";

export default function ConversationRedirect() {
  const { id } = useParams<{ id: string }>();
  redirect(`/conversations?id=${id}`);
}
