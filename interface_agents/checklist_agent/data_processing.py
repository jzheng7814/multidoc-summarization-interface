#!/usr/bin/env python3
"""Convert controller input corpora into agent-compatible document directories."""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pysbd

sys.path.insert(0, str(Path(__file__).parent))

from agent.tokenizer import TokenizerWrapper


class CorpusDataProcessor:
    """Convert one or more input corpora into the checklist agent's local data format."""

    def __init__(
        self,
        input_file: str,
        output_dir: str = "data",
        model_name: str = "Qwen/Qwen3-8B",
        verbose: bool = True,
    ):
        self.input_file = Path(input_file)
        self.output_dir = Path(output_dir)
        self.verbose = verbose
        self.dataset_name = self.input_file.stem

        self.tokenizer = TokenizerWrapper(model_name)
        if self.verbose:
            print(f"Initialized tokenizer for {model_name}")
            print(f"Tokenizer backend: {self.tokenizer._backend}")

        self.segmenter = pysbd.Segmenter(language="en", clean=False, char_span=True)
        self.stats = {
            "total_corpora": 0,
            "processed_corpora": 0,
            "total_documents": 0,
            "total_sentences": 0,
            "total_tokens": 0,
            "errors": [],
        }

    def load_data(self) -> List[Dict[str, Any]]:
        if not self.input_file.exists():
            raise FileNotFoundError(f"Input file not found: {self.input_file}")

        with self.input_file.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError("Expected list of input corpora in input file")

        self.stats["total_corpora"] = len(data)
        if self.verbose:
            print(f"Loaded {len(data)} corpora from {self.input_file}")
        return data

    def sanitize_filename(self, text: str, max_length: int = 50) -> str:
        sanitized = re.sub(r"[^\w\s-]", "", text)
        sanitized = re.sub(r"[-\s]+", "_", sanitized)
        sanitized = sanitized.lower()[:max_length]
        sanitized = sanitized.rstrip("_")
        return sanitized or "document"

    def create_document_filename(self, doc_type: str, index: int, title: str = "") -> str:
        doc_type_clean = self.sanitize_filename(doc_type, 20)
        filename = f"{doc_type_clean}_{index:03d}"
        if title:
            title_clean = self.sanitize_filename(title, 20)
            if title_clean and title_clean != doc_type_clean:
                filename = f"{filename}_{title_clean}"
        return f"{filename}.txt"

    def build_sentence_index(self, text: str) -> List[Dict[str, Any]]:
        spans = self.segmenter.segment(text)
        sentences = []
        for idx, span in enumerate(spans, start=1):
            sentence_text = text[span.start : span.end]
            sentences.append(
                {
                    "sentence_id": idx,
                    "text": sentence_text,
                    "start_char": span.start,
                    "end_char": span.end,
                }
            )
        return sentences

    def process_corpus(self, corpus: Dict[str, Any], output_base: Path) -> bool:
        try:
            corpus_id = str(corpus.get("corpus_id", "unknown"))
            corpus_dir = output_base / corpus_id
            corpus_dir.mkdir(parents=True, exist_ok=True)

            raw_documents = corpus.get("documents")
            if not isinstance(raw_documents, list) or not raw_documents:
                raise ValueError(f"Corpus {corpus_id} is missing a non-empty documents array")

            documents: List[Dict[str, Any]] = []
            for index, raw_document in enumerate(raw_documents):
                if not isinstance(raw_document, dict):
                    raise ValueError(f"Corpus {corpus_id} document {index} must be an object")
                documents.append(raw_document)

            documents_metadata = []
            total_tokens = 0
            total_sentences = 0

            for i, document in enumerate(documents):
                text = str(document.get("text") or "")
                title = str(document.get("title") or f"Document {i + 1}").strip() or f"Document {i + 1}"
                doc_type = str(document.get("doc_type") or "Unknown").strip() or "Unknown"
                date = str(document.get("date") or "").strip() or None
                doc_id = str(document.get("document_id") or f"doc_{i:03d}").strip() or f"doc_{i:03d}"

                filename = self.create_document_filename(doc_type, i + 1, title)
                doc_path = corpus_dir / filename
                with doc_path.open("w", encoding="utf-8") as f:
                    f.write(text)

                sentence_records = self.build_sentence_index(text)
                sentence_count = len(sentence_records)
                total_sentences += sentence_count
                sentence_index_filename = f"{filename}.sentences.json"
                sentence_index_path = corpus_dir / sentence_index_filename
                with sentence_index_path.open("w", encoding="utf-8") as f:
                    json.dump({"doc_id": doc_id, "sentences": sentence_records}, f, ensure_ascii=False, indent=2)

                token_count = self.tokenizer.count_tokens(text)
                total_tokens += token_count

                doc_metadata = {
                    "filename": filename,
                    "title": title,
                    "doc_type": doc_type,
                    "sentence_count": sentence_count,
                    "sentence_index_file": sentence_index_filename,
                    "token_count": token_count,
                    "doc_id": doc_id,
                }
                if date:
                    doc_metadata["date"] = date
                documents_metadata.append(doc_metadata)
                self.stats["total_documents"] += 1

            corpus_metadata = {
                "corpus_id": corpus_id,
                "document_count": len(documents),
                "total_sentences": total_sentences,
                "total_tokens": total_tokens,
                "documents": documents_metadata,
            }

            metadata_path = corpus_dir / "metadata.json"
            with metadata_path.open("w", encoding="utf-8") as f:
                json.dump(corpus_metadata, f, indent=2)

            self.stats["total_tokens"] += total_tokens
            self.stats["total_sentences"] += total_sentences
            self.stats["processed_corpora"] += 1

            if self.verbose:
                print(
                    f"✓ Processed corpus {corpus_id}: {len(documents)} documents, "
                    f"{total_sentences:,} sentences, {total_tokens:,} tokens"
                )
            return True
        except Exception as exc:  # pylint: disable=broad-except
            error_msg = f"Error processing corpus {corpus.get('corpus_id', 'unknown')}: {exc}"
            self.stats["errors"].append(error_msg)
            if self.verbose:
                print(f"✗ {error_msg}")
            return False

    def process_all(self, corpus_ids: Optional[List[str]] = None, dry_run: bool = False) -> Dict[str, Any]:
        corpora = self.load_data()

        if corpus_ids:
            corpora = [corpus for corpus in corpora if str(corpus.get("corpus_id")) in corpus_ids]
            if self.verbose:
                print(f"Processing {len(corpora)} specific corpora")

        output_base = self.output_dir / self.dataset_name
        if not dry_run:
            output_base.mkdir(parents=True, exist_ok=True)

        if self.verbose:
            print(f"Output directory: {output_base}")
            if dry_run:
                print("DRY RUN - No files will be written")
            print("-" * 60)

        for index, corpus in enumerate(corpora, start=1):
            if self.verbose and len(corpora) > 1:
                print(f"\n[{index}/{len(corpora)}] Processing corpus {corpus.get('corpus_id')}...")

            if not dry_run:
                self.process_corpus(corpus, output_base)
                continue

            raw_documents = corpus.get("documents") or []
            texts = [str(doc.get("text") or "") for doc in raw_documents if isinstance(doc, dict)]
            total_tokens = sum(self.tokenizer.count_tokens(text) for text in texts)
            self.stats["total_tokens"] += total_tokens
            self.stats["total_documents"] += len(texts)
            self.stats["processed_corpora"] += 1
            if self.verbose:
                print(f"  Would process: {len(texts)} documents, {total_tokens:,} tokens")

        if self.verbose:
            self.print_summary()
        return self.stats

    def print_summary(self) -> None:
        print("\n" + "=" * 60)
        print("Processing Summary")
        print("=" * 60)
        print(f"Total corpora: {self.stats['total_corpora']}")
        print(f"Processed corpora: {self.stats['processed_corpora']}")
        print(f"Total documents: {self.stats['total_documents']}")
        print(f"Total sentences: {self.stats['total_sentences']:,}")
        print(f"Total tokens: {self.stats['total_tokens']:,}")

        if self.stats["processed_corpora"] > 0:
            avg_docs = self.stats["total_documents"] / self.stats["processed_corpora"]
            avg_tokens = self.stats["total_tokens"] / self.stats["processed_corpora"]
            print(f"Average documents per corpus: {avg_docs:.1f}")
            print(f"Average tokens per corpus: {avg_tokens:,.0f}")

        if self.stats["errors"]:
            print(f"\nErrors encountered: {len(self.stats['errors'])}")
            for error in self.stats["errors"][:5]:
                print(f"  - {error}")
            if len(self.stats["errors"]) > 5:
                print(f"  ... and {len(self.stats['errors']) - 5} more")

    def validate_output(self, output_base: Path) -> bool:
        if not output_base.exists():
            print(f"Output directory does not exist: {output_base}")
            return False

        corpus_dirs = [directory for directory in output_base.iterdir() if directory.is_dir()]
        for corpus_dir in corpus_dirs:
            metadata_file = corpus_dir / "metadata.json"
            if not metadata_file.exists():
                print(f"Missing metadata.json in {corpus_dir}")
                return False

            try:
                with metadata_file.open("r", encoding="utf-8") as f:
                    metadata = json.load(f)

                required = ["corpus_id", "documents", "document_count", "total_sentences", "total_tokens"]
                for field in required:
                    if field not in metadata:
                        print(f"Missing field '{field}' in {metadata_file}")
                        return False

                for doc in metadata["documents"]:
                    doc_file = corpus_dir / doc["filename"]
                    if not doc_file.exists():
                        print(f"Missing document file: {doc_file}")
                        return False
                    sentence_index_file = corpus_dir / doc["sentence_index_file"]
                    if not sentence_index_file.exists():
                        print(f"Missing sentence index file: {sentence_index_file}")
                        return False
            except Exception as exc:  # pylint: disable=broad-except
                print(f"Error validating {metadata_file}: {exc}")
                return False

        print(f"✓ Validation successful: {len(corpus_dirs)} corpora validated")
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Process input corpora for checklist-agent runtime")
    parser.add_argument("input_file", help="Path to input JSON file containing controller input corpora")
    parser.add_argument("--output-dir", default="data", help="Base output directory (default: data)")
    parser.add_argument("--model", default="Qwen/Qwen3-8B", help="Model for tokenizer (default: Qwen/Qwen3-8B)")
    parser.add_argument("--corpus-ids", nargs="+", help="Specific corpus IDs to process")
    parser.add_argument("--dry-run", action="store_true", help="Perform dry run without writing files")
    parser.add_argument("--validate", action="store_true", help="Validate output after processing")
    parser.add_argument("--quiet", action="store_true", help="Suppress verbose output")
    args = parser.parse_args()

    processor = CorpusDataProcessor(
        input_file=args.input_file,
        output_dir=args.output_dir,
        model_name=args.model,
        verbose=not args.quiet,
    )
    stats = processor.process_all(corpus_ids=args.corpus_ids, dry_run=args.dry_run)

    if args.validate and not args.dry_run:
        output_base = Path(args.output_dir) / processor.dataset_name
        processor.validate_output(output_base)

    sys.exit(0 if not stats["errors"] else 1)


if __name__ == "__main__":
    main()
