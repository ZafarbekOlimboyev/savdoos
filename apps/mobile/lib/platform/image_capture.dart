import 'package:image_picker/image_picker.dart';

export 'package:image_picker/image_picker.dart' show ImageSource;

/// A picked photo: raw bytes and their MIME type.
typedef PickedImage = (List<int> bytes, String mime);

/// Invoice photo capture (camera or gallery). `image_picker` is web-safe
/// (`<input type=file capture>`), so ONE adapter.
///
/// Known gap (audit B6): `image_picker_for_web` ignores `imageQuality` and
/// `maxWidth`, so the PWA uploads the raw photo. A shared-Dart downscale
/// belongs HERE when it is added, so both platforms produce the same bytes.
abstract class ImageCapture {
  /// The active adapter (tests inject a fake).
  static ImageCapture instance = PluginImageCapture();

  /// Opens the picker; null when the operator cancelled. May throw when the
  /// platform refuses (permission) — the caller shows its own message.
  Future<PickedImage?> pick(ImageSource source);
}

/// `image_picker`-backed default (body moved verbatim from the receiving screen).
class PluginImageCapture implements ImageCapture {
  /// Creates the default.
  PluginImageCapture();

  final _picker = ImagePicker();

  @override
  Future<PickedImage?> pick(ImageSource source) async {
    final XFile? f = await _picker.pickImage(source: source, imageQuality: 70, maxWidth: 1800);
    if (f == null) return null;
    final bytes = await f.readAsBytes();
    final media = (f.mimeType != null && f.mimeType!.startsWith('image/')) ? f.mimeType! : 'image/jpeg';
    return (bytes, media);
  }
}
