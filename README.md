## About the Repository

The scripts in this repository are mostly of value to my need, I share them in case they're helpful to someone else in the spirit of openness.

## Contributing

As these scripts are custom made to fit my needs I'm not interested in broadening them to fit other peoples needs.

## `bin_link.sh`

The script is designed to automate the process of hard linking script files from the cloned directory to `$HOME/bin`.

### Key Features

- **Automated Linking:** Creates one hard link for each script file in `$HOME/bin`.
- **Suffix Removal:** The hard link has its suffix removed to make calling the script cleaner and implementation agnostic.

### Considerations

- **Filesystem Restriction:** As hard links are used the clone directory and `$HOME/bin` must reside on the same filesystem.
- **Permission Requirements:** Ensure you have the necessary permissions to create hard links in your `$HOME/bin` directory.

## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE) file for details.
