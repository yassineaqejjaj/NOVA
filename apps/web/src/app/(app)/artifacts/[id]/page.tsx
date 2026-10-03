"use client";

import { useParams } from "next/navigation";

import { ArtifactDocument } from "@/components/artifact/document";

export default function ArtifactPage() {
  const { id } = useParams<{ id: string }>();
  return <ArtifactDocument artifactId={id} />;
}
