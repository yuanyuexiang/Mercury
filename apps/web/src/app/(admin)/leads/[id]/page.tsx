"use client";
// 兼容旧链接：/leads/{id} → 工作台 /leads?id={id}
import { redirect, useParams } from "next/navigation";

export default function LeadRedirect() {
  const { id } = useParams<{ id: string }>();
  redirect(`/leads?id=${id}`);
}
