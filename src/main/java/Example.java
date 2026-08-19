import java.io.*;

public class LeakMissingClose {
    public void leakyMethod(String path) throws IOException {
        try (FileInputStream fis = new FileInputStream(path)) {
            int data = fis.read();
            System.out.println(data);
        }
    }
}
