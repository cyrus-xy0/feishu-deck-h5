// render_pdf.swift — render every page of a PDF to a PNG at a target width.
// Vector PDF (exported from Keynote/PowerPoint) → crisp PNG at any resolution
// (embedded bitmaps limited by their own native res). macOS only (PDFKit).
//   swift render_pdf.swift <input.pdf> <out_dir> <width>
import Foundation
import Quartz
import AppKit

let a = CommandLine.arguments
guard a.count >= 4 else { print("usage: render_pdf.swift <pdf> <outdir> <width>"); exit(1) }
let pdfPath = a[1], outDir = a[2]
let targetW = CGFloat(Double(a[3]) ?? 1920)
guard let doc = PDFDocument(url: URL(fileURLWithPath: pdfPath)) else { print("cannot open pdf"); exit(1) }
try? FileManager.default.createDirectory(atPath: outDir, withIntermediateDirectories: true)

for i in 0..<doc.pageCount {
    guard let page = doc.page(at: i) else { continue }
    let box = page.bounds(for: .mediaBox)
    let scale = targetW / box.width
    let w = Int(box.width * scale), h = Int(box.height * scale)
    guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8,
        bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { continue }
    ctx.setFillColor(CGColor(red: 0, green: 0, blue: 0, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
    ctx.scaleBy(x: scale, y: scale)
    ctx.translateBy(x: -box.minX, y: -box.minY)
    page.draw(with: .mediaBox, to: ctx)
    guard let cg = ctx.makeImage() else { continue }
    guard let png = NSBitmapImageRep(cgImage: cg).representation(using: .png, properties: [:]) else { continue }
    try? png.write(to: URL(fileURLWithPath: "\(outDir)/page-\(String(format: "%03d", i+1)).png"))
}
print("rendered \(doc.pageCount) pages @ width \(Int(targetW))")
