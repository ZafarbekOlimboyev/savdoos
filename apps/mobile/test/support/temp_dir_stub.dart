// Web (`flutter test --platform chrome`): there is no file system. The
// `path_provider` mock is never invoked there (the web LocalCache adapter is a
// no-op), so this is only reached by a test that explicitly asks for a path.
String tempDirPath() => throw UnsupportedError('no file system on this platform');
