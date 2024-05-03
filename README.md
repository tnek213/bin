## About the Repository

This collection comprises various small scripts I've created that have proven useful to me. While they may hold limited appeal for others, I've chosen to share them publicly in the spirit of openness and collaboration.

## File linking to a directory within $PATH

The `_link_user_bin.sh` script is designed to automate the process of hard linking script files from a source directory to a directory within $PATH. It defaults to look for a clone of this repository in `$HOME/.bin` and creating the renamed hard links in `$HOME/bin`.

### Key Features

- **Automated Linking:** Hard links script files to `$HOME/bin`.
- **Suffix Removal:** Removes programming language suffixes from script filenames in the destination directory, making them cleaner and easier to access.

### Considerations

- **Filesystem Restriction:** Due to the nature of hard links, the source directory and `$HOME/bin` must reside on the same filesystem. I might make it fallback to soft linkes if the need arises.
- **Permission Requirements:** Ensure you have the necessary permissions to create hard links in your `$HOME/bin` directory.

## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE) file for details.
